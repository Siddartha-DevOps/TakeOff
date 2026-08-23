"""Dependency-free identity normalization shared by auth and seeding."""


def normalize_email(value: str) -> str:
    return value.strip().lower()
