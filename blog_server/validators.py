"""Validators for user supplied files.

The browser-supplied `Content-Type` is never trusted: the file is opened with
Pillow, which fails on anything that is not a real image, and the format is
read from the decoded file rather than from the request.
"""

from django.conf import settings
from django.core.exceptions import ValidationError

# Raster formats we are willing to store and serve back.
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'GIF', 'WEBP'}

# Guards against decompression-bomb style uploads.
MAX_IMAGE_DIMENSION = 6000
MIN_IMAGE_DIMENSION = 16


def validate_image_upload(image):
    """Validate size, real format and dimensions of an uploaded image."""
    max_size = getattr(settings, 'MAX_IMAGE_UPLOAD_SIZE', 5 * 1024 * 1024)
    if image.size > max_size:
        raise ValidationError(
            f'Image must be smaller than {max_size // (1024 * 1024)}MB.'
        )

    # `ImageField` has already run Pillow over the upload and attached the
    # decoded dimensions/format, so re-opening the file here is unnecessary.
    image_info = getattr(image, 'image', None)
    if image_info is None:
        # A stored file being re-validated (no fresh upload to inspect).
        return

    image_format = (image_info.format or '').upper()
    if image_format not in ALLOWED_IMAGE_FORMATS:
        allowed = ', '.join(sorted(ALLOWED_IMAGE_FORMATS))
        raise ValidationError(f'Unsupported image format. Allowed formats: {allowed}.')

    width, height = image_info.size
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValidationError(
            f'Image dimensions must not exceed {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} pixels.'
        )
    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        raise ValidationError(
            f'Image must be at least {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION} pixels.'
        )
