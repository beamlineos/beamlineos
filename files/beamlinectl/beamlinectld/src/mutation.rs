// SPDX-License-Identifier: MIT
use crate::{invalid, state, state_error, sys};
use beamline_varlink::{Extension, Reply, Request};
use serde::Deserialize;
use serde_json::json;
use std::io;
use std::os::unix::net::UnixStream;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Operation {
    Enable,
    Disable,
    Activate,
    Deactivate,
}
impl Operation {
    fn action(self) -> &'static str {
        match self {
            Self::Enable => "enable",
            Self::Disable => "disable",
            Self::Activate => "activate",
            Self::Deactivate => "deactivate",
        }
    }
    fn persistent(self) -> bool {
        matches!(self, Self::Enable | Self::Disable)
    }
    fn adding(self) -> bool {
        matches!(self, Self::Enable | Self::Activate)
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct Choice {
    name: String,
    now: Option<bool>,
    allow_interactive_authentication: Option<bool>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct Live {
    name: String,
    allow_interactive_authentication: Option<bool>,
}

pub fn dispatch(request: &Request, state: &state::State, stream: Option<&UnixStream>) -> Reply {
    let op = match request.method.rsplit('.').next().unwrap() {
        "Enable" => Operation::Enable,
        "Disable" => Operation::Disable,
        "Activate" => Operation::Activate,
        "Deactivate" => Operation::Deactivate,
        _ => unreachable!(),
    };
    let (name, now, interactive) = if op.persistent() {
        let p: Choice = match serde_json::from_value(request.parameters.clone()) {
            Ok(p) => p,
            Err(_) => return invalid("parameters"),
        };
        (
            p.name,
            p.now.unwrap_or(false),
            p.allow_interactive_authentication.unwrap_or(false),
        )
    } else {
        let p: Live = match serde_json::from_value(request.parameters.clone()) {
            Ok(p) => p,
            Err(_) => return invalid("parameters"),
        };
        (
            p.name,
            true,
            p.allow_interactive_authentication.unwrap_or(false),
        )
    };
    let Some(def) = state.definitions.iter().find(|d| d.name == name) else {
        return Reply::extension_error("NoSuchExtension", json!({"name":name}));
    };
    if !op.persistent() && !def.live {
        return Reply::extension_error("NotLive", json!({"name":name}));
    }
    let authorization = (|| {
        let peer = sys::Peer::from_stream(stream.ok_or_else(|| io::Error::other("missing peer"))?)?;
        let mut bus = sys::Bus::open()?;
        let authorized = bus.authorize(&peer, op.action(), &name, interactive)?;
        Ok::<_, io::Error>((authorized, bus))
    })();
    let mut bus = match authorization {
        Ok((sys::Authorization::Authorized, bus)) => bus,
        Ok((sys::Authorization::Challenge, _)) if !interactive => {
            return Reply::extension_error("InteractiveAuthenticationRequired", json!({}));
        }
        result => {
            if let Err(error) = result {
                eprintln!("beamlinectld: authorization: {error}");
            }
            return Reply::error("org.varlink.service.PermissionDenied", json!({}));
        }
    };
    // Authentication can block on a person. Only lock after it has finished, then reread.
    let _lock = match state.lock(true) {
        Ok(lock) => lock,
        Err(error) => return state_error(error),
    };
    perform(state, def, op, now, &mut bus)
}

trait UnitControl {
    fn job(&mut self, method: &str, unit: &str) -> io::Result<()>;
}
impl UnitControl for sys::Bus {
    fn job(&mut self, method: &str, unit: &str) -> io::Result<()> {
        self.unit_job(method, unit)
    }
}

fn preflight(
    extensions: &[Extension],
    current: &Extension,
    op: Operation,
    remove_live: bool,
) -> Option<Reply> {
    if !op.adding() && current.interactive {
        let persistent_safe = !op.persistent()
            || !current.enabled
            || extensions
                .iter()
                .any(|e| e.name != current.name && e.interactive && e.enabled && e.available);
        let live_safe = !remove_live
            || extensions
                .iter()
                .any(|e| e.name != current.name && e.interactive && e.active);
        // Check before saving or creating runtime overrides, even if the live state is partial.
        if !persistent_safe || !live_safe {
            return Some(Reply::extension_error(
                "WouldLeaveNoInteractiveEnvironment",
                json!({"name":current.name}),
            ));
        }
    }
    None
}

fn failed(state: &state::State, name: &str, stage: &str, error: io::Error) -> Reply {
    match state.list().and_then(|list| {
        let current = list.into_iter().find(|e| e.name == name).unwrap();
        let (system, configuration) = state.membership(name)?;
        Ok((current, system != configuration))
    }) {
        Ok((e, partial)) => Reply::extension_error(
            "OperationFailed",
            json!({"name":name,"stage":stage,
            "message":error.to_string(),"enabled":e.enabled,"active":e.active,"rebootRequired":partial || e.enabled != e.active}),
        ),
        Err(error) => state_error(error),
    }
}

fn apply(
    state: &state::State,
    name: &str,
    active: bool,
    control: &mut impl UnitControl,
) -> Result<(), (&'static str, io::Error)> {
    let unit = format!("beamline-extension@{name}.service");
    if active {
        state
            .runtime_marker("inactive", name, false)
            .map_err(|e| ("clear-inactive", e))?;
        state
            .runtime_marker("active", name, true)
            .map_err(|e| ("mark-active", e))?;
        control.job("StartUnit", &unit).map_err(|e| ("start", e))?;
    } else {
        state
            .runtime_marker("inactive", name, true)
            .map_err(|e| ("mark-inactive", e))?;
        state
            .runtime_marker("active", name, false)
            .map_err(|e| ("clear-active", e))?;
        // The template stops CUPS first, then removes both links, even before a refresh.
        control.job("StopUnit", &unit).map_err(|e| ("stop", e))?;
        // Always unlink, including retries after an earlier failed stop/cleanup left the unit inactive.
        control
            .job(
                "StartUnit",
                &format!("beamline-extension-unlink@{name}.service"),
            )
            .map_err(|e| ("unlink", e))?;
    }
    control
        .job("StartUnit", "beamline-extensions-refresh.service")
        .map_err(|e| ("refresh", e))?;
    let (system, configuration) = state.membership(name).map_err(|e| ("verify", e))?;
    if system != active || configuration != active {
        return Err((
            "verify",
            io::Error::other(format!(
                "expected merged={active}; observed sysext={system}, confext={configuration}"
            )),
        ));
    }
    Ok(())
}

fn perform(
    state: &state::State,
    def: &state::Definition,
    op: Operation,
    now: bool,
    control: &mut impl UnitControl,
) -> Reply {
    let extensions = match state.list() {
        Ok(list) => list,
        Err(error) => return state_error(error),
    };
    let current = extensions.iter().find(|e| e.name == def.name).unwrap();
    if op.adding() && !current.available {
        return Reply::extension_error(
            "ImageMissing",
            json!({"name":def.name,"version":state.version}),
        );
    }
    let membership = match state.membership(&def.name) {
        Ok(value) => value,
        Err(error) => return state_error(error),
    };
    let remove_live = now && def.live && (membership.0 || membership.1);
    if let Some(error) = preflight(&extensions, current, op, remove_live) {
        return error;
    }
    if op.persistent() {
        if let Err(error) = state.save(def, op.adding()) {
            return failed(state, &def.name, "save", error);
        }
    }
    if now && def.live {
        if let Err((stage, error)) = apply(state, &def.name, op.adding(), control) {
            // An already durable choice is deliberately retained. Report observed live state.
            return failed(state, &def.name, stage, error);
        }
    }
    if !op.persistent() {
        return Reply::success(json!({}));
    }
    match state.list().and_then(|list| {
        let after = list.into_iter().find(|e| e.name == def.name).unwrap();
        let (system, configuration) = state.membership(&def.name)?;
        Ok((after, system != configuration))
    }) {
        Ok((after, partial)) => Reply::success(
            json!({"active":after.active,"rebootRequired":partial || after.enabled != after.active}),
        ),
        Err(error) => state_error(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn extension(name: &str, enabled: bool, active: bool, available: bool) -> Extension {
        Extension {
            name: name.into(),
            description: name.into(),
            live: name != "desktop-gnome",
            interactive: true,
            enabled,
            active,
            available,
        }
    }
    #[test]
    fn persistent_and_live_guards_use_different_evidence() {
        let posix = extension("posix", true, true, true);
        let desktop = extension("desktop-gnome", true, false, true);
        let list = [posix.clone(), desktop];
        assert!(preflight(&list, &posix, Operation::Disable, false).is_none());
        assert!(preflight(&list, &posix, Operation::Disable, true).is_some());
        assert!(preflight(&list, &posix, Operation::Deactivate, true).is_some());
        let list = [posix.clone(), extension("desktop-gnome", false, true, true)];
        assert!(preflight(&list, &posix, Operation::Deactivate, true).is_none());
        assert!(preflight(&list, &posix, Operation::Disable, true).is_some());
        let list = [posix.clone(), extension("desktop-gnome", true, true, false)];
        assert!(preflight(&list, &posix, Operation::Disable, false).is_some());
    }
    struct FailingControl;
    impl UnitControl for FailingControl {
        fn job(&mut self, _: &str, _: &str) -> io::Result<()> {
            Err(io::Error::other("injected PID 1 failure"))
        }
    }
    #[test]
    fn saved_choice_survives_live_failure_and_fs_failure_is_reported() {
        let root = std::env::temp_dir().join(format!("beamlinectl-failure-{}", std::process::id()));
        for dir in [
            "usr",
            "etc",
            "var/lib/beamline/state",
            "var/lib/beamline/extensions",
            "var/lib/beamline/confexts",
            "run/beamline/active",
            "run/beamline/inactive",
        ] {
            std::fs::create_dir_all(root.join(dir)).unwrap();
        }
        let def = state::definition(
            "posix-devel",
            "Description=Development\nLive=yes\nInteractive=no\nDefault=disabled\n",
        )
        .unwrap();
        let state = state::State {
            root: root.clone(),
            version: "test".into(),
            definitions: vec![def.clone()],
        };
        for kind in ["extensions", "confexts"] {
            std::fs::write(
                root.join(format!("var/lib/beamline/{kind}/posix-devel_test.raw")),
                "image",
            )
            .unwrap();
        }
        let reply = perform(&state, &def, Operation::Enable, true, &mut FailingControl);
        assert_eq!(
            reply.error.as_deref(),
            Some("org.beamline.Extensions.OperationFailed")
        );
        assert_eq!(reply.parameters["stage"], "start");
        assert_eq!(reply.parameters["enabled"], true);
        assert_eq!(reply.parameters["active"], false);
        assert_eq!(reply.parameters["rebootRequired"], true);
        assert!(state.enabled(&def).unwrap());
        std::fs::remove_dir_all(root.join("run/beamline/active")).unwrap();
        let reply = perform(&state, &def, Operation::Activate, true, &mut FailingControl);
        assert_eq!(reply.parameters["stage"], "mark-active");
        assert_eq!(reply.parameters["enabled"], true);
        // A saved disable must still request reboot if only one hierarchy is merged.
        use std::os::unix::fs::MetadataExt;
        std::fs::create_dir_all(root.join("usr/.systemd-sysext")).unwrap();
        let device = std::fs::metadata(root.join("usr")).unwrap().dev();
        std::fs::write(
            root.join("usr/.systemd-sysext/dev"),
            format!("{}:{}\n", libc::major(device), libc::minor(device)),
        )
        .unwrap();
        std::fs::write(root.join("usr/.systemd-sysext/extensions"), "posix-devel\n").unwrap();
        let reply = perform(&state, &def, Operation::Disable, false, &mut FailingControl);
        assert!(reply.error.is_none());
        assert_eq!(reply.parameters["active"], false);
        assert_eq!(reply.parameters["rebootRequired"], true);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn concurrent_removals_reread_under_the_same_directory_lock() {
        let root = std::env::temp_dir().join(format!("beamlinectl-race-{}", std::process::id()));
        for dir in [
            "usr",
            "etc",
            "var/lib/beamline/state",
            "var/lib/beamline/extensions",
            "var/lib/beamline/confexts",
        ] {
            std::fs::create_dir_all(root.join(dir)).unwrap();
        }
        let definitions = vec![
            state::definition(
                "desktop-gnome",
                "Description=Desktop\nLive=no\nInteractive=yes\nDefault=enabled\n",
            )
            .unwrap(),
            state::definition(
                "posix",
                "Description=POSIX\nLive=yes\nInteractive=yes\nDefault=disabled\n",
            )
            .unwrap(),
        ];
        std::fs::write(root.join("var/lib/beamline/state/posix.enabled"), "").unwrap();
        for name in ["desktop-gnome", "posix"] {
            for kind in ["extensions", "confexts"] {
                std::fs::write(
                    root.join(format!("var/lib/beamline/{kind}/{name}_test.raw")),
                    "image",
                )
                .unwrap();
            }
        }
        let ready = std::sync::Arc::new(std::sync::Barrier::new(3));
        let mut workers = Vec::new();
        for index in 0..2 {
            let state = state::State {
                root: root.clone(),
                version: "test".into(),
                definitions: definitions.clone(),
            };
            let ready = ready.clone();
            workers.push(std::thread::spawn(move || {
                ready.wait();
                let _lock = state.lock(true).unwrap();
                perform(
                    &state,
                    &state.definitions[index],
                    Operation::Disable,
                    false,
                    &mut FailingControl,
                )
                .error
                .is_none()
            }));
        }
        ready.wait();
        let successes = workers
            .into_iter()
            .map(|worker| usize::from(worker.join().unwrap()))
            .sum::<usize>();
        assert_eq!(successes, 1);
        let state = state::State {
            root: root.clone(),
            version: "test".into(),
            definitions,
        };
        assert_eq!(
            state.list().unwrap().iter().filter(|e| e.enabled).count(),
            1
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
