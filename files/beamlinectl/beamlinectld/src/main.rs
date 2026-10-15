// SPDX-License-Identifier: MIT
mod mutation;
mod state;
mod sys;
use beamline_varlink::{IDL, INTERFACE, Reply, Request, read_frame, write_message};
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::{self, BufReader};
use std::os::unix::net::UnixStream;
use std::path::Path;

const SERVICE_IDL: &str = "interface org.varlink.service\nmethod GetInfo() -> (vendor: string, product: string, version: string, url: string, interfaces: []string)\nmethod GetInterfaceDescription(interface: string) -> (description: string)\nerror InterfaceNotFound(interface: string)\nerror MethodNotFound(method: string)\nerror MethodNotImplemented(method: string)\nerror InvalidParameter(parameter: string)\nerror PermissionDenied()\n";

fn invalid(parameter: &str) -> Reply {
    Reply::error(
        "org.varlink.service.InvalidParameter",
        json!({"parameter": parameter}),
    )
}
fn state_error(error: io::Error) -> Reply {
    if error.kind() == io::ErrorKind::WouldBlock {
        Reply::extension_error("Busy", json!({}))
    } else {
        Reply::extension_error("StateUnavailable", json!({"message":error.to_string()}))
    }
}

fn dispatch(request: &Request, state: &state::State, stream: Option<&UnixStream>) -> Reply {
    if request.more || request.upgrade {
        return Reply::error(
            "org.varlink.service.MethodNotImplemented",
            json!({"method": request.method}),
        );
    }
    match request.method.as_str() {
        "org.varlink.service.GetInfo" if request.parameters == json!({}) => Reply::success(json!({
            "vendor":"Beamline", "product":"beamlinectld", "version":env!("CARGO_PKG_VERSION"),
            "url":"https://github.com/c-lin-chunyi/beamline", "interfaces":[INTERFACE],
        })),
        "org.varlink.service.GetInterfaceDescription" => {
            #[derive(Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Params {
                interface: String,
            }
            match serde_json::from_value::<Params>(request.parameters.clone()) {
                Ok(p) => match p.interface.as_str() {
                    INTERFACE => Reply::success(json!({"description":IDL})),
                    "org.varlink.service" => Reply::success(json!({"description":SERVICE_IDL})),
                    _ => Reply::error(
                        "org.varlink.service.InterfaceNotFound",
                        json!({"interface":p.interface}),
                    ),
                },
                Err(_) => invalid("interface"),
            }
        }
        "org.beamline.Extensions.List" if request.parameters == json!({}) => {
            let _lock = match state.lock(false) {
                Ok(lock) => lock,
                Err(error) => return state_error(error),
            };
            match state.list() {
                Ok(extensions) => Reply::success(json!({"extensions":extensions})),
                Err(error) => state_error(error),
            }
        }
        "org.varlink.service.GetInfo" | "org.beamline.Extensions.List" => invalid("parameters"),
        "org.beamline.Extensions.Enable"
        | "org.beamline.Extensions.Disable"
        | "org.beamline.Extensions.Activate"
        | "org.beamline.Extensions.Deactivate" => mutation::dispatch(request, state, stream),
        method => {
            let interface = method.rsplit_once('.').map(|(i, _)| i).unwrap_or(method);
            if interface != INTERFACE && interface != "org.varlink.service" {
                Reply::error(
                    "org.varlink.service.InterfaceNotFound",
                    json!({"interface":interface}),
                )
            } else {
                Reply::error(
                    "org.varlink.service.MethodNotFound",
                    json!({"method":method}),
                )
            }
        }
    }
}

fn serve(stream: UnixStream, state: &state::State) -> io::Result<()> {
    let timeout = Some(std::time::Duration::from_secs(30));
    stream.set_read_timeout(timeout)?;
    stream.set_write_timeout(timeout)?;
    let mut stream = BufReader::new(stream);
    while let Some(frame) = read_frame(&mut stream)? {
        let request: Request = match serde_json::from_slice(&frame) {
            Ok(value) => value,
            Err(_) => {
                write_message(stream.get_mut(), &invalid("request"))?;
                continue;
            }
        };
        let reply = dispatch(&request, state, Some(stream.get_ref()));
        if !request.oneway {
            write_message(stream.get_mut(), &reply)?;
        }
    }
    Ok(())
}

fn main() {
    let stream = match sys::activated_stream() {
        Ok(stream) => stream,
        Err(error) => {
            eprintln!("beamlinectld: {error}");
            std::process::exit(1);
        }
    };
    let state = match state::State::load(Path::new("/")) {
        Ok(state) => state,
        Err(e) => {
            eprintln!("beamlinectld: cannot load platform metadata: {e}");
            std::process::exit(1);
        }
    };
    // Malformed frames, disconnects and client timeouts must not mark the system degraded.
    if let Err(e) = serve(stream, &state) {
        eprintln!("beamlinectld: connection closed: {e}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn state() -> state::State {
        state::State {
            root: "/nonexistent".into(),
            version: "test".into(),
            definitions: vec![],
        }
    }
    #[test]
    fn introspection_and_errors_are_structured() {
        let call = |method: &str, parameters: Value| {
            dispatch(
                &Request {
                    method: method.into(),
                    parameters,
                    more: false,
                    oneway: false,
                    upgrade: false,
                },
                &state(),
                None,
            )
        };
        assert!(
            call("org.varlink.service.GetInfo", json!({}))
                .error
                .is_none()
        );
        assert_eq!(
            call("org.varlink.service.GetInfo", json!({"command":"sh"}))
                .error
                .unwrap(),
            "org.varlink.service.InvalidParameter"
        );
        assert_eq!(
            call(
                "org.varlink.service.GetInterfaceDescription",
                json!({"interface":INTERFACE})
            )
            .parameters["description"],
            IDL
        );
        assert_eq!(
            call("org.beamline.Extensions.Activate", json!({"name":"posix"}))
                .error
                .unwrap(),
            "org.beamline.Extensions.NoSuchExtension"
        );
        assert_eq!(
            call("org.beamline.Extensions.Enable", json!({"name":"../posix"}))
                .error
                .unwrap(),
            "org.beamline.Extensions.NoSuchExtension"
        );
        assert_eq!(
            call(
                "org.beamline.Extensions.Enable",
                json!({"name":"posix", "command":"sh"})
            )
            .error
            .unwrap(),
            "org.varlink.service.InvalidParameter"
        );
        assert_eq!(
            call(
                "org.beamline.Extensions.Activate",
                json!({"name":"posix", "now":false})
            )
            .error
            .unwrap(),
            "org.varlink.service.InvalidParameter"
        );
        assert_eq!(
            call(
                "org.beamline.Extensions.Disable",
                json!({"name":"posix", "now":"yes"})
            )
            .error
            .unwrap(),
            "org.varlink.service.InvalidParameter"
        );
        assert_eq!(
            call("org.other.List", json!({})).error.unwrap(),
            "org.varlink.service.InterfaceNotFound"
        );
    }
}
