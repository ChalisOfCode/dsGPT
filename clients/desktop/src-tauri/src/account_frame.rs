// Frames never enter a file, diagnostic event or error message.
pub const MAX_PNG: usize = 1_572_864;

pub fn valid_id(id: &str) -> bool {
    id.len() == 36 && id.bytes().enumerate().all(|(i, b)| {
        if [8, 13, 18, 23].contains(&i) { b == b'-' } else { b.is_ascii_hexdigit() }
    })
}

pub fn valid_png(data: &[u8]) -> bool {
    data.len() >= 33 && data.len() <= MAX_PNG
        && data[..8] == *b"\x89PNG\r\n\x1a\n"
        && data[8..16] == [0, 0, 0, 13, b'I', b'H', b'D', b'R']
        && data[16..24] == [0, 0, 4, 0, 0, 0, 3, 0] // fixed 1024 x 768
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_wrong_identity_and_frame_bounds() {
        assert!(valid_id("00000000-0000-4000-8000-000000000001"));
        assert!(!valid_id("------------------------------------"));
        assert!(!valid_id("00000000/0000-4000-8000-000000000001"));
        let mut frame = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\x04\0\0\0\x03\0".to_vec();
        frame.resize(33, 0);
        assert!(valid_png(&frame));
        frame[16] = 127;
        assert!(!valid_png(&frame));
        frame[16] = 0;
        frame.resize(MAX_PNG + 1, 0);
        assert!(!valid_png(&frame));
        assert!(!valid_png(b"not a frame"));
    }
}
