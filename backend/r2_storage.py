"""
Cloudflare R2 Storage Integration
Handles photo uploads to R2 object storage
"""

import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import uuid
from datetime import datetime
from io import BytesIO
from PIL import Image

# R2 Configuration from environment (sanitized at runtime)
_DEFAULT_R2_ENDPOINT = 'https://845e544c36651c4aa2c720ffe2a0278d.r2.cloudflarestorage.com'
_DEFAULT_R2_ACCESS_KEY = '454a9d25b6d4790706d7cd63e7a81ffb'
_DEFAULT_R2_SECRET_KEY = 'a6c09057302bc6cd80851b8c64cab4c74e5428c062903b0af631d6b7b085e3e3'
_DEFAULT_R2_BUCKET = 'borescope-photos'
_DEFAULT_R2_PUBLIC_URL = 'https://pub-5e14ffe08d36478ab37dd33a0222a43e.r2.dev'

# S3 client initialized lazily to avoid errors on import
_s3_client = None
_config_cache = None

def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().strip('"').strip("'")
    return value if value else default

def get_r2_config():
    """Return sanitized R2 configuration and reset client if config changes."""
    global _s3_client, _config_cache
    cfg = {
        "endpoint": _get_env('R2_ENDPOINT', _DEFAULT_R2_ENDPOINT).rstrip('/'),
        "access_key": _get_env('R2_ACCESS_KEY', _DEFAULT_R2_ACCESS_KEY),
        "secret_key": _get_env('R2_SECRET_KEY', _DEFAULT_R2_SECRET_KEY),
        "bucket": _get_env('R2_BUCKET', _DEFAULT_R2_BUCKET),
        "public_url": _get_env('R2_PUBLIC_URL', _DEFAULT_R2_PUBLIC_URL).rstrip('/'),
    }

    if _config_cache is None or cfg != _config_cache:
        _config_cache = cfg
        _s3_client = None
    return _config_cache

def get_s3_client():
    """Get or create S3 client for R2"""
    global _s3_client
    cfg = get_r2_config()
    if _s3_client is None:
        _s3_client = boto3.client(
            's3',
            endpoint_url=cfg["endpoint"],
            aws_access_key_id=cfg["access_key"],
            aws_secret_access_key=cfg["secret_key"],
            config=Config(signature_version='s3v4'),
            region_name='auto'
        )
    return _s3_client

def optimize_image(image_bytes: bytes, max_size_mb: float = 2.0, quality: int = 85) -> bytes:
    """
    Optimize image size while maintaining quality
    Args:
        image_bytes: Original image bytes
        max_size_mb: Maximum file size in MB
        quality: JPEG quality (1-100)
    Returns:
        Optimized image bytes
    """
    try:
        img = Image.open(BytesIO(image_bytes))
        
        # Convert RGBA to RGB if needed
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        
        # Resize if too large
        max_dimension = 1920
        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        
        # Save with optimization
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        optimized_bytes = output.getvalue()
        
        # Check size and reduce quality if needed
        max_bytes = max_size_mb * 1024 * 1024
        current_quality = quality
        while len(optimized_bytes) > max_bytes and current_quality > 50:
            current_quality -= 10
            output = BytesIO()
            img.save(output, format='JPEG', quality=current_quality, optimize=True)
            optimized_bytes = output.getvalue()
        
        print(f"✅ Image optimized: {len(image_bytes)} → {len(optimized_bytes)} bytes (quality={current_quality})")
        return optimized_bytes
    
    except Exception as e:
        print(f"⚠️ Image optimization failed: {e}, using original")
        return image_bytes


def upload_photo_to_r2(file_bytes: bytes, inspection_id: int, photo_index: int, photo_num: int) -> str:
    """
    Upload photo to R2 and return public URL
    Args:
        file_bytes: Photo file bytes
        inspection_id: Borescope inspection ID
        photo_index: Index of photo row (0, 1, 2...)
        photo_num: Photo number in row (1 or 2)
    Returns:
        Public URL of uploaded photo
    """
    try:
        cfg = get_r2_config()

        # Optimize image before upload
        optimized_bytes = optimize_image(file_bytes)

        # Generate unique filename
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        filename = f"borescope/{inspection_id}/{timestamp}_{photo_index}_{photo_num}_{unique_id}.jpg"

        # Upload to R2
        get_s3_client().put_object(
            Bucket=cfg["bucket"],
            Key=filename,
            Body=optimized_bytes,
            ContentType='image/jpeg',
            CacheControl='public, max-age=31536000'
        )

        # Construct public URL
        public_url = f"{cfg['public_url']}/{filename}"
        return public_url

    except ClientError as e:
        error_code = e.response['Error'].get('Code', 'Unknown')
        error_msg = e.response['Error'].get('Message', 'No message')
        raise Exception(f"Failed to upload photo to R2: {error_code} - {error_msg}")
    except Exception as e:
        raise Exception(f"Failed to upload photo: {str(e)}")


def delete_photo_from_r2(photo_url: str) -> bool:
    """
    Delete photo from R2 by URL
    Args:
        photo_url: Public URL of photo
    Returns:
        True if deleted successfully
    """
    try:
        cfg = get_r2_config()

        # Extract filename from URL
        filename = photo_url.replace(cfg["public_url"] + '/', '')

        # Delete from R2
        get_s3_client().delete_object(
            Bucket=cfg["bucket"],
            Key=filename
        )
        
        return True
    
    except Exception as e:
        return False


def get_file(file_path: str) -> bytes:
    """
    Download file from R2 by path
    Args:
        file_path: File path in R2 (e.g. 'borescope/123/file.jpg')
    Returns:
        File content as bytes, or None if not found
    """
    try:
        cfg = get_r2_config()

        # Download from R2
        response = get_s3_client().get_object(
            Bucket=cfg["bucket"],
            Key=file_path
        )
        
        file_content = response['Body'].read()
        return file_content
    
    except ClientError:
        return None
    except Exception:
        return None


def test_r2_connection() -> bool:
    """
    Test R2 connection and bucket access
    Returns:
        True if connection successful
    """
    try:
        cfg = get_r2_config()
        # Try to list objects in bucket
        get_s3_client().list_objects_v2(Bucket=cfg["bucket"], MaxKeys=1)
        return True
    except ClientError:
        return False
    except Exception as e:
        print(f"❌ R2 connection error: {e}")
        return False
