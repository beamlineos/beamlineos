// SPDX-License-Identifier: MIT
use beamline_varlink::Extension;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

pub const NAMES: [&str; 4] = ["desktop-gnome", "posix", "posix-devel", "printing-scanning"];

#[derive(Clone, Debug)]
pub struct Definition {
    pub name: String,
    pub description: String,
    pub live: bool,
    pub interactive: bool,
    pub default_enabled: bool,
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

pub fn definition(name: &str, text: &str) -> io::Result<Definition> {
    if !NAMES.contains(&name) {
        return Err(invalid("unknown extension"));
    }
    let mut keys = BTreeMap::new();
    for line in text
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
    {
        let (key, value) = line
            .split_once('=')
            .ok_or_else(|| invalid("expected Key=Value"))?;
        if !["Description", "Live", "Interactive", "Default"].contains(&key)
            || keys.insert(key, value).is_some()
        {
            return Err(invalid("unknown or repeated metadata key"));
        }
    }
    let get = |key| {
        keys.get(key)
            .copied()
            .ok_or_else(|| invalid(format!("missing {key}")))
    };
    let boolean = |key| match get(key)? {
        "yes" => Ok(true),
        "no" => Ok(false),
        _ => Err(invalid("expected yes or no")),
    };
    Ok(Definition {
        name: name.to_owned(),
        description: get("Description")?.to_owned(),
        live: boolean("Live")?,
        interactive: boolean("Interactive")?,
        default_enabled: match get("Default")? {
            "enabled" => true,
            "disabled" => false,
            _ => return Err(invalid("invalid default")),
        },
    })
}

pub struct State {
    pub root: PathBuf,
    pub version: String,
    pub definitions: Vec<Definition>,
}
impl State {
    pub fn load(root: &Path) -> io::Result<Self> {
        let release = fs::read_to_string(root.join("usr/lib/os-release"))?;
        let version = release
            .lines()
            .find_map(|l| l.strip_prefix("IMAGE_VERSION="))
            .map(|s| s.trim_matches('"').to_owned())
            .ok_or_else(|| invalid("IMAGE_VERSION missing"))?;
        if version.is_empty()
            || !version
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
        {
            return Err(invalid("invalid IMAGE_VERSION"));
        }
        let definitions = NAMES
            .into_iter()
            .map(|name| {
                definition(
                    name,
                    &fs::read_to_string(
                        root.join(format!("usr/lib/beamline/extensions.d/{name}.conf")),
                    )?,
                )
            })
            .collect::<io::Result<_>>()?;
        Ok(Self {
            root: root.to_owned(),
            version,
            definitions,
        })
    }
    pub fn path(&self, relative: &str) -> PathBuf {
        self.root.join(relative)
    }
    pub fn lock(&self, exclusive: bool) -> io::Result<fs::File> {
        let directory = fs::File::open(self.path("var/lib/beamline/state"))?;
        let started = std::time::Instant::now();
        loop {
            if crate::sys::try_lock(&directory, exclusive)? {
                return Ok(directory);
            }
            if started.elapsed() >= std::time::Duration::from_secs(5) {
                return Err(io::Error::new(
                    io::ErrorKind::WouldBlock,
                    "extension state is busy",
                ));
            }
            std::thread::sleep(std::time::Duration::from_millis(25));
        }
    }
    pub fn save(&self, def: &Definition, enabled: bool) -> io::Result<()> {
        if self.enabled(def)? == enabled {
            return Ok(());
        }
        let directory = fs::File::open(self.path("var/lib/beamline/state"))?;
        let suffix = if def.default_enabled {
            "disabled"
        } else {
            "enabled"
        };
        let marker = self.path(&format!("var/lib/beamline/state/{}.{suffix}", def.name));
        if enabled != def.default_enabled {
            fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .custom_flags(libc::O_NOFOLLOW)
                .open(marker)?
                .sync_all()?;
        } else {
            fs::remove_file(marker)?;
        }
        directory.sync_all()
    }
    pub fn enabled(&self, def: &Definition) -> io::Result<bool> {
        let suffix = if def.default_enabled {
            "disabled"
        } else {
            "enabled"
        };
        let path = self.path(&format!("var/lib/beamline/state/{}.{suffix}", def.name));
        match fs::symlink_metadata(path) {
            Ok(meta) if meta.is_file() && meta.len() == 0 => Ok(!def.default_enabled),
            Ok(_) => Err(invalid("choice marker must be an empty regular file")),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(def.default_enabled),
            Err(e) => Err(e),
        }
    }
    pub fn available(&self, name: &str) -> io::Result<bool> {
        let mut available = true;
        for kind in ["extensions", "confexts"] {
            match fs::metadata(self.path(&format!(
                "var/lib/beamline/{kind}/{name}_{}.raw",
                self.version
            ))) {
                Ok(meta) => available &= meta.is_file(),
                Err(e) if e.kind() == io::ErrorKind::NotFound => available = false,
                Err(e) => return Err(e),
            }
        }
        Ok(available)
    }
    pub fn runtime_marker(&self, directory: &str, name: &str, present: bool) -> io::Result<()> {
        if !["active", "inactive"].contains(&directory) || !NAMES.contains(&name) {
            return Err(invalid("invalid runtime marker"));
        }
        let path = self.path(&format!("run/beamline/{directory}/{name}"));
        if present {
            match fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .custom_flags(libc::O_NOFOLLOW)
                .open(&path)
            {
                Ok(_) => Ok(()),
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                    let meta = fs::symlink_metadata(path)?;
                    if meta.is_file() && meta.len() == 0 {
                        Ok(())
                    } else {
                        Err(invalid("invalid runtime marker"))
                    }
                }
                Err(e) => Err(e),
            }
        } else {
            match fs::remove_file(path) {
                Ok(()) => Ok(()),
                Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
                Err(e) => Err(e),
            }
        }
    }
    pub fn membership(&self, name: &str) -> io::Result<(bool, bool)> {
        Ok((
            merged(&self.path("usr"), ".systemd-sysext")?.contains(name),
            merged(&self.path("etc"), ".systemd-confext")?.contains(name),
        ))
    }
    pub fn list(&self) -> io::Result<Vec<Extension>> {
        let sysext = merged(&self.path("usr"), ".systemd-sysext")?;
        let confext = merged(&self.path("etc"), ".systemd-confext")?;
        self.definitions
            .iter()
            .map(|def| {
                Ok(Extension {
                    name: def.name.clone(),
                    description: def.description.clone(),
                    live: def.live,
                    interactive: def.interactive,
                    enabled: self.enabled(def)?,
                    active: sysext.contains(&def.name) && confext.contains(&def.name),
                    available: self.available(&def.name)?,
                })
            })
            .collect()
    }
}

                                                                                          
fn merged(hierarchy: &Path, directory: &str) -> io::Result<BTreeSet<String>> {
    let device = match fs::read_to_string(hierarchy.join(directory).join("dev")) {
        Ok(value) => value,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(BTreeSet::new()),
        Err(e) => return Err(e),
    };
    let (major, minor) = device
        .trim()
        .split_once(':')
        .ok_or_else(|| invalid("invalid merge device"))?;
    let major = major
        .parse::<u32>()
        .map_err(|_| invalid("invalid merge device"))?;
    let minor = minor
        .parse::<u32>()
        .map_err(|_| invalid("invalid merge device"))?;
    let dev = fs::metadata(hierarchy)?.dev();
    if libc::major(dev) != major || libc::minor(dev) != minor {
        return Ok(BTreeSet::new());
    }
    let list = if directory == ".systemd-confext" {
        "confexts"
    } else {
        "extensions"
    };
    Ok(fs::read_to_string(hierarchy.join(directory).join(list))?
        .lines()
        .map(str::to_owned)
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn metadata_is_closed_and_requires_explicit_flags() {
        let text = "Description=POSIX\nLive=yes\nInteractive=yes\nDefault=disabled\n";
        assert!(!definition("posix", text).unwrap().default_enabled);
        assert!(definition("../posix", text).is_err());
        assert!(definition("posix", &(text.to_owned() + "Live=no\n")).is_err());
        assert!(definition("posix", &(text.to_owned() + "Command=sh\n")).is_err());
        assert!(definition("posix", "Description=POSIX\n").is_err());
    }
    #[test]
    fn choices_availability_and_real_merge_membership_are_independent() {
        let root = std::env::temp_dir().join(format!("beamlinectl-state-{}", std::process::id()));
        fs::create_dir_all(root.join("usr/.systemd-sysext")).unwrap();
        fs::create_dir_all(root.join("etc/.systemd-confext")).unwrap();
        fs::create_dir_all(root.join("var/lib/beamline/state")).unwrap();
        fs::create_dir_all(root.join("var/lib/beamline/extensions")).unwrap();
        fs::create_dir_all(root.join("var/lib/beamline/confexts")).unwrap();
        let state = State {
            root: root.clone(),
            version: "test".into(),
            definitions: vec![
                definition(
                    "desktop-gnome",
                    "Description=Desktop\nLive=no\nInteractive=yes\nDefault=enabled\n",
                )
                .unwrap(),
                definition(
                    "posix",
                    "Description=POSIX\nLive=yes\nInteractive=yes\nDefault=disabled\n",
                )
                .unwrap(),
            ],
        };
        assert!(state.list().unwrap()[0].enabled);
        assert!(!state.list().unwrap()[1].enabled);
        fs::write(root.join("var/lib/beamline/state/posix.enabled"), "").unwrap();
        assert!(state.list().unwrap()[1].enabled);
        state.save(&state.definitions[1], false).unwrap();
        assert!(!state.list().unwrap()[1].enabled);
        state.save(&state.definitions[1], true).unwrap();
        state.save(&state.definitions[1], true).unwrap();
        assert!(state.list().unwrap()[1].enabled);
        let lock = state.lock(true).unwrap();
        let other = fs::File::open(root.join("var/lib/beamline/state")).unwrap();
        assert!(!crate::sys::try_lock(&other, true).unwrap());
        drop(lock);
        assert!(crate::sys::try_lock(&other, false).unwrap());
        drop(other);
        fs::write(
            root.join("var/lib/beamline/extensions/posix_test.raw"),
            "image",
        )
        .unwrap();
        assert!(!state.list().unwrap()[1].available);
        fs::write(
            root.join("var/lib/beamline/confexts/posix_test.raw"),
            "image",
        )
        .unwrap();
        assert!(state.list().unwrap()[1].available);
        for (hierarchy, directory) in [("usr", ".systemd-sysext"), ("etc", ".systemd-confext")] {
            let dev = fs::metadata(root.join(hierarchy)).unwrap().dev();
            fs::write(
                root.join(hierarchy).join(directory).join("dev"),
                format!("{}:{}\n", libc::major(dev), libc::minor(dev)),
            )
            .unwrap();
            let list = if directory == ".systemd-confext" {
                "confexts"
            } else {
                "extensions"
            };
            fs::write(root.join(hierarchy).join(directory).join(list), "posix\n").unwrap();
        }
        assert!(state.list().unwrap()[1].active);
        fs::write(root.join("etc/.systemd-confext/dev"), "0:0\n").unwrap();
        assert!(!state.list().unwrap()[1].active);
        fs::write(root.join("var/lib/beamline/state/posix.enabled"), "invalid").unwrap();
        assert!(state.list().is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
