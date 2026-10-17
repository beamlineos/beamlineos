// SPDX-License-Identifier: MIT
                                                                                        
#![deny(unsafe_op_in_unsafe_fn)]
use std::ffi::{CStr, CString, c_char, c_int, c_void};
use std::io;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::net::UnixStream;

#[repr(C)]
struct SdBus {
    _private: [u8; 0],
}
#[repr(C)]
struct SdMessage {
    _private: [u8; 0],
}
#[repr(C)]
struct SdError {
    name: *const c_char,
    message: *const c_char,
    need_free: c_int,
}

#[link(name = "systemd")]
unsafe extern "C" {
    fn sd_bus_open_system(bus: *mut *mut SdBus) -> c_int;
    fn sd_bus_flush_close_unref(bus: *mut SdBus) -> *mut SdBus;
    fn sd_bus_message_unref(message: *mut SdMessage) -> *mut SdMessage;
    fn sd_bus_message_new_method_call(
        bus: *mut SdBus,
        message: *mut *mut SdMessage,
        destination: *const c_char,
        path: *const c_char,
        interface: *const c_char,
        member: *const c_char,
    ) -> c_int;
    fn sd_bus_message_open_container(
        message: *mut SdMessage,
        kind: c_char,
        contents: *const c_char,
    ) -> c_int;
    fn sd_bus_message_close_container(message: *mut SdMessage) -> c_int;
    fn sd_bus_message_append_basic(
        message: *mut SdMessage,
        kind: c_char,
        value: *const c_void,
    ) -> c_int;
    fn sd_bus_call(
        bus: *mut SdBus,
        message: *mut SdMessage,
        timeout: u64,
        error: *mut SdError,
        reply: *mut *mut SdMessage,
    ) -> c_int;
    fn sd_bus_message_enter_container(
        message: *mut SdMessage,
        kind: c_char,
        contents: *const c_char,
    ) -> c_int;
    fn sd_bus_message_read_basic(
        message: *mut SdMessage,
        kind: c_char,
        value: *mut c_void,
    ) -> c_int;
    fn sd_bus_error_free(error: *mut SdError) -> *mut SdError;
}

fn check(result: c_int) -> io::Result<()> {
    if result < 0 {
        Err(io::Error::from_raw_os_error(-result))
    } else {
        Ok(())
    }
}
fn string(value: &str) -> io::Result<CString> {
    CString::new(value)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "NUL in D-Bus string"))
}

pub struct Peer {
    pub uid: u32,
    pidfd: OwnedFd,
}
impl Peer {
    pub fn from_stream(stream: &UnixStream) -> io::Result<Self> {
        let mut credentials = libc::ucred {
            pid: 0,
            uid: 0,
            gid: 0,
        };
        let mut size = std::mem::size_of_val(&credentials) as libc::socklen_t;
        
        if unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERCRED,
                (&mut credentials as *mut libc::ucred).cast(),
                &mut size,
            )
        } < 0
        {
            return Err(io::Error::last_os_error());
        }
        if size as usize != std::mem::size_of_val(&credentials) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid peer credentials",
            ));
        }
        let mut descriptor: c_int = -1;
        size = std::mem::size_of_val(&descriptor) as libc::socklen_t;
        
        
        if unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERPIDFD,
                (&mut descriptor as *mut c_int).cast(),
                &mut size,
            )
        } < 0
        {
            return Err(io::Error::last_os_error());
        }
        if descriptor < 0 {
            return Err(io::Error::other("missing peer pidfd"));
        }
        
        Ok(Self {
            uid: credentials.uid,
            pidfd: unsafe { OwnedFd::from_raw_fd(descriptor) },
        })
    }
}

pub fn activated_stream() -> io::Result<UnixStream> {
    if std::env::var("LISTEN_FDS").as_deref() != Ok("1")
        || std::env::var("LISTEN_PID")
            .ok()
            .and_then(|v| v.parse::<u32>().ok())
            != Some(std::process::id())
    {
        return Err(io::Error::other("expected one socket-activated connection"));
    }
    
    Ok(unsafe { UnixStream::from_raw_fd(3) })
}

pub fn try_lock(file: &std::fs::File, exclusive: bool) -> io::Result<bool> {
    let operation = if exclusive {
        libc::LOCK_EX
    } else {
        libc::LOCK_SH
    };
    
    if unsafe { libc::flock(file.as_raw_fd(), operation | libc::LOCK_NB) } == 0 {
        return Ok(true);
    }
    let error = io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::EWOULDBLOCK) {
        Ok(false)
    } else {
        Err(error)
    }
}

pub struct Bus(*mut SdBus, bool);
struct Message(*mut SdMessage);
impl Drop for Bus {
    fn drop(&mut self) {
        
        unsafe {
            sd_bus_flush_close_unref(self.0);
        }
    }
}
impl Drop for Message {
    fn drop(&mut self) {
        
        unsafe {
            sd_bus_message_unref(self.0);
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum Authorization {
    Authorized,
    Challenge,
    Denied,
}

impl Message {
    fn open(&mut self, kind: u8, contents: &str) -> io::Result<()> {
        let signature = string(contents)?;
        
        check(unsafe { sd_bus_message_open_container(self.0, kind as c_char, signature.as_ptr()) })
    }
    fn close(&mut self) -> io::Result<()> {
        
        check(unsafe { sd_bus_message_close_container(self.0) })
    }
    fn text(&mut self, value: &str) -> io::Result<()> {
        let value = string(value)?;
        
        check(unsafe { sd_bus_message_append_basic(self.0, b's' as c_char, value.as_ptr().cast()) })
    }
    fn integer(&mut self, kind: u8, value: &c_int) -> io::Result<()> {
        
        
        check(unsafe {
            sd_bus_message_append_basic(self.0, kind as c_char, (value as *const c_int).cast())
        })
    }
    fn enter(&mut self, kind: u8, contents: &str) -> io::Result<()> {
        let signature = string(contents)?;
        
        let result =
            unsafe { sd_bus_message_enter_container(self.0, kind as c_char, signature.as_ptr()) };
        check(result)?;
        if result == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "missing D-Bus container",
            ));
        }
        Ok(())
    }
    fn boolean(&mut self) -> io::Result<bool> {
        let mut value: c_int = 0;
        
        let result = unsafe {
            sd_bus_message_read_basic(self.0, b'b' as c_char, (&mut value as *mut c_int).cast())
        };
        check(result)?;
        if result == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "missing D-Bus boolean",
            ));
        }
        Ok(value != 0)
    }
}

impl Bus {
    pub fn open() -> io::Result<Self> {
        let mut bus = std::ptr::null_mut();
        
        check(unsafe { sd_bus_open_system(&mut bus) })?;
        Ok(Self(bus, false))
    }
    fn method(
        &mut self,
        destination: &str,
        path: &str,
        interface: &str,
        member: &str,
    ) -> io::Result<Message> {
        let (destination, path, interface, member) = (
            string(destination)?,
            string(path)?,
            string(interface)?,
            string(member)?,
        );
        let mut message = std::ptr::null_mut();
        
        check(unsafe {
            sd_bus_message_new_method_call(
                self.0,
                &mut message,
                destination.as_ptr(),
                path.as_ptr(),
                interface.as_ptr(),
                member.as_ptr(),
            )
        })?;
        Ok(Message(message))
    }
    fn call(&mut self, message: &mut Message) -> io::Result<Message> {
        let mut error = SdError {
            name: std::ptr::null(),
            message: std::ptr::null(),
            need_free: 0,
        };
        let mut reply = std::ptr::null_mut();
        
        let result = unsafe { sd_bus_call(self.0, message.0, 120_000_000, &mut error, &mut reply) };
        let detail = if !error.message.is_null() {
            
            Some(
                unsafe { CStr::from_ptr(error.message) }
                    .to_string_lossy()
                    .into_owned(),
            )
        } else {
            None
        };
        
        unsafe {
            sd_bus_error_free(&mut error);
        }
        if result < 0 {
            if !reply.is_null() {
                drop(Message(reply));
            }
            return Err(detail
                .map(io::Error::other)
                .unwrap_or_else(|| io::Error::from_raw_os_error(-result)));
        }
        if reply.is_null() {
            return Err(io::Error::other("D-Bus call returned no reply"));
        }
        Ok(Message(reply))
    }
    pub fn authorize(
        &mut self,
        peer: &Peer,
        operation: &str,
        name: &str,
        interactive: bool,
    ) -> io::Result<Authorization> {
        let mut message = self.method(
            "org.freedesktop.PolicyKit1",
            "/org/freedesktop/PolicyKit1/Authority",
            "org.freedesktop.PolicyKit1.Authority",
            "CheckAuthorization",
        )?;
        message.open(b'r', "sa{sv}")?;
        message.text("unix-process")?;
        message.open(b'a', "{sv}")?;
        for (key, kind, value) in [
            ("pidfd", b'h', peer.pidfd.as_raw_fd()),
            ("uid", b'i', peer.uid as i32),
        ] {
            message.open(b'e', "sv")?;
            message.text(key)?;
            message.open(b'v', std::str::from_utf8(&[kind]).unwrap())?;
            message.integer(kind, &value)?;
            message.close()?;
            message.close()?;
        }
        message.close()?;
        message.close()?;
        message.text(&format!("org.beamline.extensions.{operation}"))?;
        message.open(b'a', "{ss}")?;
        message.open(b'e', "ss")?;
        message.text("name")?;
        message.text(name)?;
        message.close()?;
        message.close()?;
        message.integer(b'u', &i32::from(interactive))?;
        message.text("")?;
        let mut reply = self.call(&mut message)?;
        reply.enter(b'r', "bba{ss}")?;
        let authorized = reply.boolean()?;
        let challenge = reply.boolean()?;
        Ok(if authorized {
            Authorization::Authorized
        } else if challenge {
            Authorization::Challenge
        } else {
            Authorization::Denied
        })
    }
}


#[repr(C)]
struct SdSlot {
    _private: [u8; 0],
}
type Handler = unsafe extern "C" fn(*mut SdMessage, *mut c_void, *mut SdError) -> c_int;
#[link(name = "systemd")]
unsafe extern "C" {
    fn sd_bus_add_match(
        bus: *mut SdBus,
        slot: *mut *mut SdSlot,
        expression: *const c_char,
        callback: Handler,
        userdata: *mut c_void,
    ) -> c_int;
    fn sd_bus_slot_unref(slot: *mut SdSlot) -> *mut SdSlot;
    fn sd_bus_process(bus: *mut SdBus, message: *mut *mut SdMessage) -> c_int;
    fn sd_bus_wait(bus: *mut SdBus, timeout: u64) -> c_int;
}
struct Slot(*mut SdSlot);
impl Drop for Slot {
    fn drop(&mut self) {
        
        unsafe {
            sd_bus_slot_unref(self.0);
        }
    }
}
struct JobEvents {
    unit: String,
    results: std::collections::VecDeque<(String, String)>,
}

unsafe extern "C" fn job_removed(
    message: *mut SdMessage,
    userdata: *mut c_void,
    _error: *mut SdError,
) -> c_int {
    
    
    unsafe {
        let mut id = 0u32;
        let (mut path, mut unit, mut result): (*const c_char, *const c_char, *const c_char) =
            (std::ptr::null(), std::ptr::null(), std::ptr::null());
        if sd_bus_message_read_basic(message, b'u' as c_char, (&mut id as *mut u32).cast()) <= 0
            || sd_bus_message_read_basic(
                message,
                b'o' as c_char,
                (&mut path as *mut *const c_char).cast(),
            ) <= 0
            || sd_bus_message_read_basic(
                message,
                b's' as c_char,
                (&mut unit as *mut *const c_char).cast(),
            ) <= 0
            || sd_bus_message_read_basic(
                message,
                b's' as c_char,
                (&mut result as *mut *const c_char).cast(),
            ) <= 0
            || path.is_null()
            || unit.is_null()
            || result.is_null()
        {
            return 0;
        }
        let events = &mut *userdata.cast::<JobEvents>();
        if CStr::from_ptr(unit).to_bytes() == events.unit.as_bytes() {
            if events.results.len() == 64 {
                events.results.pop_front();
            }
            events.results.push_back((
                CStr::from_ptr(path).to_string_lossy().into_owned(),
                CStr::from_ptr(result).to_string_lossy().into_owned(),
            ));
        }
    }
    0
}

impl Message {
    fn read_text(&mut self, kind: u8) -> io::Result<String> {
        let mut value: *const c_char = std::ptr::null();
        
        let result = unsafe {
            sd_bus_message_read_basic(
                self.0,
                kind as c_char,
                (&mut value as *mut *const c_char).cast(),
            )
        };
        check(result)?;
        if result == 0 || value.is_null() {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "missing D-Bus string",
            ));
        }
        
        Ok(unsafe { CStr::from_ptr(value) }
            .to_string_lossy()
            .into_owned())
    }
}

impl Bus {
    pub fn unit_job(&mut self, method: &str, unit: &str) -> io::Result<()> {
        if !["StartUnit", "StopUnit"].contains(&method) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "unsupported unit operation",
            ));
        }
        if !self.1 {
            let mut subscribe = self.method(
                "org.freedesktop.systemd1",
                "/org/freedesktop/systemd1",
                "org.freedesktop.systemd1.Manager",
                "Subscribe",
            )?;
            self.call(&mut subscribe)?;
            self.1 = true;
        }
        let mut events = Box::new(JobEvents {
            unit: unit.to_owned(),
            results: std::collections::VecDeque::new(),
        });
        let expression = string(
            "type='signal',sender='org.freedesktop.systemd1',path='/org/freedesktop/systemd1',interface='org.freedesktop.systemd1.Manager',member='JobRemoved'",
        )?;
        let mut slot = std::ptr::null_mut();
        
        check(unsafe {
            sd_bus_add_match(
                self.0,
                &mut slot,
                expression.as_ptr(),
                job_removed,
                (&mut *events as *mut JobEvents).cast(),
            )
        })?;
        let _slot = Slot(slot);
        let mut request = self.method(
            "org.freedesktop.systemd1",
            "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager",
            method,
        )?;
        request.text(unit)?;
        request.text("replace")?;
        let job = self.call(&mut request)?.read_text(b'o')?;
        let started = std::time::Instant::now();
        loop {
            if let Some((_, result)) = events.results.iter().find(|(path, _)| path == &job) {
                return if result == "done" {
                    Ok(())
                } else {
                    Err(io::Error::other(format!("{unit}: job {result}")))
                };
            }
            if started.elapsed() >= std::time::Duration::from_secs(120) {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    format!("timed out waiting for {unit}"),
                ));
            }
            
            let processed = unsafe { sd_bus_process(self.0, std::ptr::null_mut()) };
            check(processed)?;
            if processed == 0 {
                
                check(unsafe { sd_bus_wait(self.0, 100_000) })?;
            }
        }
    }
}
