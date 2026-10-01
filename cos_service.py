import os
import sys
from qcloud_cos import CosConfig, CosS3Client

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

load_env()

SECRET_ID = os.environ.get('COS_SECRET_ID')
SECRET_KEY = os.environ.get('COS_SECRET_KEY')
REGION = os.environ.get('COS_REGION', 'ap-hongkong')
BUCKET = os.environ.get('COS_BUCKET', 'tony-rc-1-1381711719')

if SECRET_ID and SECRET_KEY:
    try:
        config = CosConfig(Region=REGION, SecretId=SECRET_ID, SecretKey=SECRET_KEY)
        client = CosS3Client(config)
    except Exception:
        client = None
else:
    client = None

def test_cos_connection():
    try:
        response = client.head_bucket(Bucket=BUCKET)
        print(f"COS Connection Success! Bucket '{BUCKET}' in region '{REGION}' is reachable.")
        return True
    except Exception as e:
        print(f"COS Connection Error: {e}")
        return False

def upload_file_to_cos(local_file_path: str, cos_target_path: str) -> str:
    """
    Uploads a local file to Tencent COS, automatically sets public-read ACL,
    and returns the public CDN URL.
    """
    if not client:
        raise ValueError("COS secret key not configured")
    try:
        cos_target_path = cos_target_path.lstrip('/')
        
        client.upload_file(
            Bucket=BUCKET,
            LocalFilePath=local_file_path,
            Key=cos_target_path,
            PartSize=1,
            MAXThread=5,
            EnableMD5=False
        )
        
        # Ensure the object is publicly readable for browser HTML5 video/audio playback
        try:
            client.put_object_acl(Bucket=BUCKET, Key=cos_target_path, ACL='public-read')
        except Exception as acl_e:
            print(f"ACL Notice for {cos_target_path}: {acl_e}")

        cdn_url = f"https://{BUCKET}.cos.{REGION}.myqcloud.com/{cos_target_path}"
        return cdn_url
    except Exception as e:
        print(f"Failed to upload {local_file_path} to COS: {e}")
        raise e

if __name__ == '__main__':
    test_cos_connection()
