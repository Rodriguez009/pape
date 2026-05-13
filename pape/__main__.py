import warnings

# Python 3.9 ships with LibreSSL; urllib3 v2 warns at import time. Harmless for our use.
warnings.filterwarnings("ignore", message=r".*OpenSSL.*", category=Warning)
try:
    from urllib3.exceptions import NotOpenSSLWarning
    warnings.simplefilter("ignore", NotOpenSSLWarning)
except Exception:
    pass

from .cli import main

if __name__ == "__main__":
    main()
