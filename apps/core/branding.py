import os

DEFAULT_PRODUCT_NAME = "Home Command Center"
DEFAULT_SHORT_NAME = "HCC"


def product_name():
    configured = os.environ.get("HCC_PRODUCT_NAME", "").strip()
    return configured or DEFAULT_PRODUCT_NAME


def product_short_name():
    configured = os.environ.get("HCC_PRODUCT_SHORT_NAME", "").strip()
    return configured or DEFAULT_SHORT_NAME


def product_info(version):
    return {
        "product": product_name(),
        "shortName": product_short_name(),
        "version": version,
        "releaseChannel": os.environ.get("HCC_RELEASE_CHANNEL", "stable"),
    }
