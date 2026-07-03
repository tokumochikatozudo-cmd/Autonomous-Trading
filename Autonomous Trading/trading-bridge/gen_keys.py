from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import os

# Generate private key
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)

# Serialize private key to PEM format
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

# Extract public key
public_key = private_key.public_key()
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)

base_path = r"c:\Autonomous Trading\trading-bridge"
with open(os.path.join(base_path, ".bybit_private.pem"), "wb") as f:
    f.write(private_pem)

with open(os.path.join(base_path, ".bybit_public.pem"), "wb") as f:
    f.write(public_pem)

print(public_pem.decode('utf-8'))
