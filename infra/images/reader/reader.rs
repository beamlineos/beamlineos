// SPDX-License-Identifier: BSD-3-Clause
// Ported from desync index.go, format.go, readseeker.go and chunk.go:
// ad89f62cc216376f1747dae60f74a890f0a53940 (v1.1.4).
// Copyright (c) 2017, folbricht. See LICENSE.desync for the complete notice.
// HTTP and store I/O stay outside this platform-independent reader.
use sha2::{Digest, Sha512_256};
use std::io::Read;
use std::slice;

const INDEX: u64 = 0x96824d9c7b129ff9;
const TABLE: u64 = 0xe75b9e112f17417d;
const TAIL: u64 = 0x4b4f050e5549ecd1;
const SHA512_256: u64 = 0x8000000000000000;

struct Chunk {
    end: u64,
    id: [u8; 32],
}
pub struct Index {
    chunks: Vec<Chunk>,
}
fn word(b: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(b[at..at + 8].try_into().unwrap())
}

#[no_mangle]
pub extern "C" fn alloc(len: u32) -> *mut u8 {
    Box::into_raw(vec![0u8; len as usize].into_boxed_slice()) as *mut u8
}
#[no_mangle]
pub unsafe extern "C" fn free(ptr: *mut u8, len: u32) {
    drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(
        ptr,
        len as usize,
    )));
}

fn parse(b: &[u8]) -> Option<Index> {
    if b.len() < 104
        || (b.len() - 104) % 40 != 0
        || word(b, 0) != 48
        || word(b, 8) != INDEX
        || word(b, 16) != (SHA512_256 | 0x3000000000000000)
        || word(b, 48) != u64::MAX
        || word(b, 56) != TABLE
    {
        return None;
    }
    let max = word(b, 40);
    if max != 262144 || word(b, 24) != 16384 || word(b, 32) != 65536 {
        return None;
    }
    let tail = b.len() - 40;
    if word(b, tail) != 0
        || word(b, tail + 8) != 0
        || word(b, tail + 16) != 48
        || word(b, tail + 24) != (b.len() - 48) as u64
        || word(b, tail + 32) != TAIL
    {
        return None;
    }
    let mut chunks = Vec::with_capacity((b.len() - 104) / 40);
    let mut previous = 0;
    for at in (64..tail).step_by(40) {
        let end = word(b, at);
        if end <= previous || end - previous > max {
            return None;
        }
        chunks.push(Chunk {
            end,
            id: b[at + 8..at + 40].try_into().ok()?,
        });
        previous = end;
    }
    Some(Index { chunks })
}

#[no_mangle]
pub unsafe extern "C" fn load_index(ptr: *const u8, len: u32) -> *mut Index {
    match parse(slice::from_raw_parts(ptr, len as usize)) {
        Some(index) => Box::into_raw(Box::new(index)),
        None => std::ptr::null_mut(),
    }
}
#[no_mangle]
pub unsafe extern "C" fn drop_index(index: *mut Index) {
    drop(Box::from_raw(index));
}
#[no_mangle]
pub unsafe extern "C" fn chunk_count(index: *const Index) -> u32 {
    (*index).chunks.len() as u32
}
#[no_mangle]
pub unsafe extern "C" fn image_size(index: *const Index) -> u64 {
    (*index).chunks.last().map_or(0, |c| c.end)
}
#[no_mangle]
pub unsafe extern "C" fn chunk_start(index: *const Index, n: u32) -> u64 {
    if n == 0 {
        0
    } else {
        (&(*index).chunks)[n as usize - 1].end
    }
}
#[no_mangle]
pub unsafe extern "C" fn chunk_end(index: *const Index, n: u32) -> u64 {
    (&(*index).chunks)[n as usize].end
}
#[no_mangle]
pub unsafe extern "C" fn chunk_id(index: *const Index, n: u32) -> *const u8 {
    (&(*index).chunks)[n as usize].id.as_ptr()
}

// Writes (chunk index, skip bytes, take bytes) triples. The last chunk is clipped
// to the range's end, and the first is found with the same bisection as desync.
#[no_mangle]
pub unsafe extern "C" fn read_plan(
    index: *const Index,
    start: u64,
    length: u64,
    output: *mut u32,
    capacity: u32,
) -> i32 {
    let idx = &*index;
    let size = idx.chunks.last().map_or(0, |c| c.end);
    let Some(end) = start.checked_add(length) else {
        return -1;
    };
    if start > size || end > size {
        return -1;
    }
    if length == 0 {
        return 0;
    }
    let first = idx.chunks.partition_point(|chunk| chunk.end <= start);
    let mut n = 0usize;
    let mut position = start;
    for i in first..idx.chunks.len() {
        if position >= end {
            break;
        }
        if n >= capacity as usize {
            return -2;
        }
        let base = if i == 0 { 0 } else { idx.chunks[i - 1].end };
        let stop = idx.chunks[i].end.min(end);
        output.add(n * 3).write(i as u32);
        output.add(n * 3 + 1).write((position - base) as u32);
        output.add(n * 3 + 2).write((stop - position) as u32);
        n += 1;
        position = stop;
    }
    n as i32
}

#[no_mangle]
pub unsafe extern "C" fn verify_chunk(
    index: *const Index,
    n: u32,
    ptr: *const u8,
    len: u32,
) -> u32 {
    let idx = &*index;
    let Some(chunk) = idx.chunks.get(n as usize) else {
        return 0;
    };
    let base = if n == 0 {
        0
    } else {
        idx.chunks[n as usize - 1].end
    };
    if chunk.end - base != len as u64 {
        return 0;
    }
    let digest = Sha512_256::digest(slice::from_raw_parts(ptr, len as usize));
    u32::from(digest.as_slice() == chunk.id)
}

// Reuse ruzstd's decoder, bounded to one indexed chunk.
// Returns a decoded buffer pointer, or null; the caller frees exactly `expected`.
#[no_mangle]
pub unsafe extern "C" fn decode_chunk(input: *const u8, len: u32, expected: u32) -> *mut u8 {
    if expected == 0 || expected > 262144 || len > 300000 {
        return std::ptr::null_mut();
    }
    let source = slice::from_raw_parts(input, len as usize);
    let decoder = match ruzstd::decoding::StreamingDecoder::new(source) {
        Ok(decoder) => decoder,
        Err(_) => return std::ptr::null_mut(),
    };
    let mut plain = Vec::with_capacity(expected as usize);
    if decoder
        .take(expected as u64 + 1)
        .read_to_end(&mut plain)
        .is_err()
        || plain.len() != expected as usize
    {
        return std::ptr::null_mut();
    }
    Box::into_raw(plain.into_boxed_slice()) as *mut u8
}
