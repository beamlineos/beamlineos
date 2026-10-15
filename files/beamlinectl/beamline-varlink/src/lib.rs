// SPDX-License-Identifier: MIT
//! The synchronous varlink client shared by the CLI and the future GUI. No D-Bus dependency.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::fmt;
use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;

pub const INTERFACE: &str = "org.beamline.Extensions";
pub const SOCKET: &str = "/run/beamline/org.beamline.Extensions";
pub const IDL: &str = include_str!("../../org.beamline.Extensions.varlink");
pub const MAX_FRAME: usize = 64 * 1024;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub method: String,
    #[serde(default = "empty_object")]
    pub parameters: Value,
    #[serde(default)]
    pub more: bool,
    #[serde(default)]
    pub oneway: bool,
    #[serde(default)]
    pub upgrade: bool,
}

pub fn empty_object() -> Value {
    json!({})
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Extension {
    pub name: String,
    pub description: String,
    pub live: bool,
    pub interactive: bool,
    pub enabled: bool,
    pub active: bool,
    pub available: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ChoiceResult {
    pub active: bool,
    pub reboot_required: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Reply {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(default = "empty_object")]
    pub parameters: Value,
}

impl Reply {
    pub fn success(parameters: Value) -> Self {
        Self {
            error: None,
            parameters,
        }
    }
    pub fn error(error: &str, parameters: Value) -> Self {
        Self {
            error: Some(error.to_owned()),
            parameters,
        }
    }
    pub fn extension_error(error: &str, parameters: Value) -> Self {
        Self::error(&format!("{INTERFACE}.{error}"), parameters)
    }
}

/// Bound memory before appending input, including an unterminated frame.
pub fn read_frame<R: BufRead>(reader: &mut R) -> io::Result<Option<Vec<u8>>> {
    let mut frame = Vec::new();
    loop {
        let bytes = reader.fill_buf()?;
        if bytes.is_empty() {
            return if frame.is_empty() {
                Ok(None)
            } else {
                Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "unterminated varlink frame",
                ))
            };
        }
        let end = bytes.iter().position(|b| *b == 0);
        let take = end.unwrap_or(bytes.len());
        if take > MAX_FRAME - frame.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "varlink frame exceeds 64 KiB",
            ));
        }
        frame.extend_from_slice(&bytes[..take]);
        reader.consume(take + usize::from(end.is_some()));
        if end.is_some() {
            return Ok(Some(frame));
        }
    }
}

pub fn write_message<W: Write, T: Serialize>(writer: &mut W, value: &T) -> io::Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > MAX_FRAME {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "varlink reply exceeds 64 KiB",
        ));
    }
    writer.write_all(&bytes)?;
    writer.write_all(&[0])?;
    writer.flush()
}

#[derive(Debug)]
pub enum Error {
    Io(io::Error),
    Protocol(String),
    Remote(Reply),
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => e.fmt(f),
            Self::Protocol(e) => f.write_str(e),
            Self::Remote(reply) => write!(
                f,
                "{}: {}",
                reply.error.as_deref().unwrap_or("error"),
                reply.parameters
            ),
        }
    }
}
impl std::error::Error for Error {}
impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}

pub struct Client {
    stream: BufReader<UnixStream>,
}
impl Client {
    pub fn connect() -> Result<Self, Error> {
        Self::connect_to(SOCKET)
    }
    pub fn connect_to(path: impl AsRef<std::path::Path>) -> Result<Self, Error> {
        let stream = UnixStream::connect(path)?;
        let timeout = Some(std::time::Duration::from_secs(600));
        stream.set_read_timeout(timeout)?;
        stream.set_write_timeout(timeout)?;
        Ok(Self {
            stream: BufReader::new(stream),
        })
    }
    pub fn call(&mut self, method: &str, parameters: Value) -> Result<Value, Error> {
        write_message(
            self.stream.get_mut(),
            &json!({"method": method, "parameters": parameters}),
        )?;
        let frame = read_frame(&mut self.stream)?
            .ok_or_else(|| Error::Protocol("server closed without a reply".into()))?;
        let reply: Reply =
            serde_json::from_slice(&frame).map_err(|e| Error::Protocol(e.to_string()))?;
        if reply.error.is_some() {
            return Err(Error::Remote(reply));
        }
        Ok(reply.parameters)
    }
    pub fn list(&mut self) -> Result<Vec<Extension>, Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct List {
            extensions: Vec<Extension>,
        }
        let value = self.call(&format!("{INTERFACE}.List"), json!({}))?;
        let result: List =
            serde_json::from_value(value).map_err(|e| Error::Protocol(e.to_string()))?;
        Ok(result.extensions)
    }
    pub fn set_enabled(
        &mut self,
        name: &str,
        enabled: bool,
        now: bool,
        interactive: bool,
    ) -> Result<ChoiceResult, Error> {
        let method = if enabled { "Enable" } else { "Disable" };
        let value = self.call(
            &format!("{INTERFACE}.{method}"),
            json!({
                "name":name, "now":now, "allowInteractiveAuthentication":interactive,
            }),
        )?;
        serde_json::from_value(value).map_err(|error| Error::Protocol(error.to_string()))
    }
    pub fn set_active(&mut self, name: &str, active: bool, interactive: bool) -> Result<(), Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Empty {}
        let method = if active { "Activate" } else { "Deactivate" };
        let value = self.call(
            &format!("{INTERFACE}.{method}"),
            json!({
                "name":name, "allowInteractiveAuthentication":interactive,
            }),
        )?;
        serde_json::from_value::<Empty>(value)
            .map_err(|error| Error::Protocol(error.to_string()))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    #[test]
    fn framing_handles_fragmentation_multiple_frames_and_truncation() {
        let mut reader = BufReader::with_capacity(2, Cursor::new(b"{}\0[]\0"));
        assert_eq!(read_frame(&mut reader).unwrap().unwrap(), b"{}");
        assert_eq!(read_frame(&mut reader).unwrap().unwrap(), b"[]");
        assert!(read_frame(&mut reader).unwrap().is_none());
        assert_eq!(
            read_frame(&mut Cursor::new(b"{")).unwrap_err().kind(),
            io::ErrorKind::UnexpectedEof
        );
    }
    #[test]
    fn framing_bounds_unterminated_and_terminated_messages() {
        for suffix in [vec![], vec![0]] {
            let mut data = vec![b'x'; MAX_FRAME + 1];
            data.extend(suffix);
            assert_eq!(
                read_frame(&mut Cursor::new(data)).unwrap_err().kind(),
                io::ErrorKind::InvalidData
            );
        }
        let mut data = vec![b'x'; MAX_FRAME];
        data.push(0);
        assert_eq!(
            read_frame(&mut Cursor::new(data)).unwrap().unwrap().len(),
            MAX_FRAME
        );
    }
    #[test]
    fn request_rejects_unknown_duplicate_and_mistyped_fields() {
        for text in [
            r#"{"method":"x","command":"sh"}"#,
            r#"{"method":"a","method":"b"}"#,
            r#"{"method":"x","more":1}"#,
        ] {
            assert!(serde_json::from_str::<Request>(text).is_err());
        }
    }
}
