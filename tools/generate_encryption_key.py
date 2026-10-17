"""Run privately on the host; put output only in Railway KAOS_KEY_ENCRYPTION_KEY."""
from cryptography.fernet import Fernet
if __name__ == '__main__':
    print(Fernet.generate_key().decode())
