import os

from storages.backends.s3boto3 import S3Boto3Storage


class MediaRootS3Storage(S3Boto3Storage):
    location = os.environ.get("AWS_LOCATION", "media")

    def _strip_location_prefix(self, name):
        if not name:
            return name

        normalized = str(name).lstrip("/")
        location_prefix = f"{self.location.strip('/')}/"
        if normalized.startswith(location_prefix):
            return normalized[len(location_prefix):]
        return normalized

    def _save(self, name, content):
        return super()._save(self._strip_location_prefix(name), content)

    def url(self, name, parameters=None, expire=None, http_method=None):
        return super().url(
            self._strip_location_prefix(name),
            parameters=parameters,
            expire=expire,
            http_method=http_method,
        )
