"""Authentication module."""
import hashlib
import os
from typing import Optional
from dataclasses import dataclass

@dataclass
class User:
    username: str
    password_hash: str
    role: str = "user"

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash a password with a random salt."""
    if salt is None:
        salt = os.urandom(16).hex()
    h = hashlib.sha256((password + salt).encode()).hexdigest()
    return h, salt

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a password against stored hash."""
    computed, _ = hash_password(password, salt)
    return computed == stored_hash

def create_user(username: str, password: str) -> User:
    h, salt = hash_password(password)
    return User(username=username, password_hash=f"{h}:{salt}")

class AuthService:
    def __init__(self):
        self._users: dict[str, User] = {}

    def register(self, username: str, password: str) -> User:
        if username in self._users:
            raise ValueError(f"User {username} already exists")
        user = create_user(username, password)
        self._users[username] = user
        return user

    def authenticate(self, username: str, password: str) -> bool:
        user = self._users.get(username)
        if user is None:
            return False
        h, salt = user.password_hash.split(":")
        return verify_password(password, h, salt)
