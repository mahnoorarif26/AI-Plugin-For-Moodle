"""LTI (Learning Tools Interoperability) utilities."""

import base64
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


def generate_rsa_keys():
    """
    Generate RSA key pair for LTI 1.3.
    
    Returns:
        dict: JWKS data containing public key information
    """
    try:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        
        public_numbers = private_key.public_key().public_numbers()
        n_b64 = base64.urlsafe_b64encode(
            public_numbers.n.to_bytes(256, byteorder='big')
        ).decode('utf-8').rstrip('=')
        e_b64 = base64.urlsafe_b64encode(
            public_numbers.e.to_bytes(4, byteorder='big')
        ).decode('utf-8').rstrip('=')
        
        jwks_data = {
            "keys": [
                {
                    "kty": "RSA",
                    "alg": "RS256", 
                    "use": "sig",
                    "kid": "lti-key-1",
                    "n": n_b64,
                    "e": e_b64
                }
            ]
        }
        
        print("✅ LTI RSA keys generated")
        return jwks_data
        
    except Exception as e:
        print(f"⚠️ Using placeholder keys: {e}")
        return {
            "keys": [{
                "kty": "RSA",
                "alg": "RS256", 
                "use": "sig",
                "kid": "test-key",
                "n": "placeholder_n",
                "e": "AQAB"
            }]
        }


# Initialize LTI keys
LTI_JWKS = generate_rsa_keys()