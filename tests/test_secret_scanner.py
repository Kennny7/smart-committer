from smart_committer.secret_scanner import SecretScanner


def test_detect_private_key():
    dummy_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
    findings = SecretScanner.scan_text(dummy_key)
    assert len(findings) > 0
    assert findings[0].rule_id == "private-key"


def test_detect_aws_token():
    text = "aws_secret_access_key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'"
    findings = SecretScanner.scan_text(text)
    assert len(findings) > 0
    assert findings[0].rule_id == "aws-secret-key"


def test_detect_database_url():
    text = "DATABASE_URL = 'postgres://user:supersecretpassword123@localhost:5432/mydb'"
    findings = SecretScanner.scan_text(text)
    assert len(findings) > 0
    assert findings[0].rule_id == "db-connection-string"


def test_clean_text_passes():
    text = "def calculate_sum(a: int, b: int) -> int:\n    return a + b"
    findings = SecretScanner.scan_text(text)
    assert len(findings) == 0


def test_sensitive_filenames():
    assert SecretScanner.is_sensitive_filename(".env")
    assert SecretScanner.is_sensitive_filename(".env.production")
    assert SecretScanner.is_sensitive_filename("id_rsa")
    assert SecretScanner.is_sensitive_filename("server.pem")
    assert not SecretScanner.is_sensitive_filename(".env.example")
    assert not SecretScanner.is_sensitive_filename("README.md")
