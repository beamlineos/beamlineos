// SPDX-License-Identifier: MIT
use beamline_varlink::{Client, Error};
use serde_json::json;
use std::io::{IsTerminal, Read};
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::process::{Child, Command, Stdio};

struct Agent(Child);
impl Drop for Agent {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
impl Agent {
    fn start() -> std::io::Result<Self> {
        let (mut ready, notify) = UnixStream::pair()?;
        ready.set_read_timeout(Some(std::time::Duration::from_secs(30)))?;
        let mut agent = Agent(
            Command::new("/usr/bin/pkttyagent")
                .args(["--notify-fd", "1", "--fallback"])
                .stdout(Stdio::from(OwnedFd::from(notify)))
                .spawn()?,
        );
        
        let mut byte = [0u8];
        while ready.read(&mut byte)? != 0 {}
        if agent.0.try_wait()?.is_some() {
            return Err(std::io::Error::other("authentication agent exited"));
        }
        Ok(agent)
    }
}

fn report(error: Error, json_output: bool) -> i32 {
    if json_output {
        match &error {
            Error::Remote(reply) => eprintln!("{}", serde_json::to_string(reply).unwrap()),
            _ => eprintln!(
                "{}",
                json!({"error":"ConnectionFailed","parameters":{"message":error.to_string()}})
            ),
        }
    } else if let Error::Remote(reply) = &error {
        if reply.error.as_deref() == Some("org.beamline.Extensions.OperationFailed") {
            let p = &reply.parameters;
            eprintln!(
                "beamlinectl: {}: saved choice={}; active={}; failed at {}: {}",
                p["name"].as_str().unwrap_or("extension"),
                if p["enabled"] == true {
                    "enabled"
                } else {
                    "disabled"
                },
                p["active"],
                p["stage"].as_str().unwrap_or("operation"),
                p["message"].as_str().unwrap_or("unknown failure")
            );
            if p["rebootRequired"] == true {
                eprintln!("The saved choice still requires a reboot or a successful live retry.");
            }
        } else {
            eprintln!("beamlinectl: {error}");
        }
    } else {
        eprintln!("beamlinectl: {error}");
    }
    1
}

fn usage() {
    println!(
        "Usage: beamlinectl [--json] [--no-ask-password] list|enable NAME [--now]|disable NAME [--now]|activate NAME|deactivate NAME"
    );
}

fn run() -> i32 {
    let mut json_output = false;
    let mut ask = true;
    let mut now = false;
    let mut words = Vec::new();
    for arg in std::env::args().skip(1) {
        match arg.as_str() {
            "--json" => json_output = true,
            "--now" => now = true,
            "--no-ask-password" => ask = false,
            "--help" | "-h" => {
                usage();
                return 0;
            }
            _ => words.push(arg),
        }
    }
    let valid = words == ["list"]
        || words.len() == 2
            && ["enable", "disable", "activate", "deactivate"].contains(&words[0].as_str());
    if !valid
        || now && !["enable", "disable"].contains(&words[0].as_str())
        || words.iter().any(|word| word.starts_with('-'))
    {
        usage();
        return 2;
    }
    let mutate = words[0] != "list";
    let interactive = mutate && ask && std::io::stdin().is_terminal();
    let _agent = if interactive {
        match Agent::start() {
            Ok(agent) => Some(agent),
            Err(error) => return report(Error::Io(error), json_output),
        }
    } else {
        None
    };
    let mut client = match Client::connect() {
        Ok(client) => client,
        Err(error) => return report(error, json_output),
    };
    if mutate {
        if ["activate", "deactivate"].contains(&words[0].as_str()) {
            return match client.set_active(&words[1], words[0] == "activate", interactive) {
                Ok(()) => {
                    if json_output {
                        println!("{{}}");
                    } else {
                        println!(
                            "{}: {} for this boot. Saved choice unchanged.",
                            words[1],
                            if words[0] == "activate" {
                                "active"
                            } else {
                                "inactive"
                            }
                        );
                    }
                    0
                }
                Err(error) => report(error, json_output),
            };
        }
        return match client.set_enabled(&words[1], words[0] == "enable", now, interactive) {
            Ok(result) => {
                if json_output {
                    println!("{}", serde_json::to_string(&result).unwrap());
                } else {
                    println!(
                        "{}: saved choice={}; active={}",
                        words[1],
                        if words[0] == "enable" {
                            "enabled"
                        } else {
                            "disabled"
                        },
                        result.active
                    );
                    if result.reboot_required {
                        println!("Reboot to apply the saved choice.");
                    }
                }
                0
            }
            Err(error) => report(error, json_output),
        };
    }
    match client.list() {
        Ok(extensions) if json_output => {
            println!("{}", json!({"extensions":extensions}));
            0
        }
        Ok(extensions) => {
            println!("EXTENSION         ENABLED ACTIVE AVAILABLE LIVE");
            for ext in extensions {
                let flag = |b| if b { "yes" } else { "no" };
                println!(
                    "{:<17} {:<7} {:<6} {:<9} {}",
                    ext.name,
                    flag(ext.enabled),
                    flag(ext.active),
                    flag(ext.available),
                    flag(ext.live)
                );
            }
            0
        }
        Err(error) => report(error, json_output),
    }
}

fn main() {
    std::process::exit(run());
}
