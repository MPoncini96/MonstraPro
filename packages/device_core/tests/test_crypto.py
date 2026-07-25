from device_core.config import load_config
from device_core.crypto import Encryptor, get_encryptor, load_or_create_device_key


def test_device_key_persists_across_calls(tmp_path):
    config = load_config(overrides={"data_dir": str(tmp_path)})

    key1 = load_or_create_device_key(config.device_key_path)
    key2 = load_or_create_device_key(config.device_key_path)

    assert key1 == key2
    assert config.device_key_path.exists()


def test_encrypt_decrypt_roundtrip(tmp_path):
    config = load_config(overrides={"data_dir": str(tmp_path)})
    encryptor = get_encryptor(config)

    token = encryptor.encrypt("super-secret-alpaca-key")

    assert token != "super-secret-alpaca-key"
    assert encryptor.decrypt(token) == "super-secret-alpaca-key"


def test_different_keys_cannot_decrypt_each_other(tmp_path):
    config_a = load_config(overrides={"data_dir": str(tmp_path / "a")})
    config_b = load_config(overrides={"data_dir": str(tmp_path / "b")})

    encryptor_a = get_encryptor(config_a)
    encryptor_b = Encryptor(load_or_create_device_key(config_b.device_key_path))

    token = encryptor_a.encrypt("secret")
    try:
        encryptor_b.decrypt(token)
    except Exception:
        pass
    else:
        raise AssertionError("decrypting with the wrong device key should fail")
