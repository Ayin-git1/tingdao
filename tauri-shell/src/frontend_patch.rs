use ed25519_dalek::{Signature, VerifyingKey};
use std::io::Read;

fn verify(public: &[u8; 32], message: &[u8], signature: &[u8]) -> bool {
    let (Ok(key), Ok(signature)) = (VerifyingKey::from_bytes(public), Signature::from_slice(signature)) else {
        return false;
    };
    key.verify_strict(message, &signature).is_ok()
}

pub fn verify_cli() -> i32 {
    fn run() -> Option<bool> {
        let args: Vec<_> = std::env::args_os().collect();
        if args.len() != 4 { return None; }
        let hex = include_str!("../../frontend-patch-public-key.hex").trim();
        if hex.len() != 64 || !hex.is_ascii() { return None; }
        let mut public = [0; 32];
        for (i, byte) in public.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&hex[i*2..i*2+2], 16).ok()?;
        }
        let mut message = Vec::new();
        std::fs::File::open(&args[2]).ok()?.take(65537).read_to_end(&mut message).ok()?;
        let mut signature = Vec::new();
        std::fs::File::open(&args[3]).ok()?.take(65).read_to_end(&mut signature).ok()?;
        if message.len() > 65536 || signature.len() != 64 { return None; }
        Some(verify(&public, &message, &signature))
    }
    if run() == Some(true) { 0 } else { 1 }
}

#[cfg(test)]
mod tests {
    #[test]
    fn signatures_are_bound_to_message_and_key() {
        use ed25519_dalek::{Signer, SigningKey};
        let key = SigningKey::from_bytes(&[42; 32]);
        let signature = key.sign(b"manifest");
        assert!(super::verify(&key.verifying_key().to_bytes(), b"manifest", &signature.to_bytes()));
        assert!(!super::verify(&key.verifying_key().to_bytes(), b"tampered", &signature.to_bytes()));
        assert!(!super::verify(&[0; 32], b"manifest", &signature.to_bytes()));
        assert!(!super::verify(&key.verifying_key().to_bytes(), b"manifest", &[0; 63]));
    }
}
