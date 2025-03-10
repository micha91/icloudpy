import dataclasses
from enum import Enum
from typing import Union


class AssetVersionSize(Enum):
    ORIGINAL = "original"
    ADJUSTED = "adjusted"
    ALTERNATIVE = "alternative"
    MEDIUM = "medium"
    THUMB = "thumb"

    def __str__(self) -> str:
        return self.name


class LivePhotoVersionSize(Enum):
    ORIGINAL = "originalVideo"
    MEDIUM = "mediumVideo"
    THUMB = "smallVideo"

    def __str__(self) -> str:
        return self.name


class AssetItemType(Enum):
    MOVIE = "movie"
    IMAGE = "image"

    def __str__(self) -> str:
        return self.name


@dataclasses.dataclass
class AssetVersion:
    filename: str
    size: int | None = None
    url: str | None = None
    type: str | None = None
    width: int | None = None
    height: str | None = None
    checksum: str | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AssetVersion):
            # don"t attempt to compare against unrelated types
            return NotImplemented
        return (
            self.filename == other.filename
            and self.size == other.size
            and self.url == other.url
            and self.type == other.type
        )


VersionSize = Union[AssetVersionSize, LivePhotoVersionSize]


PHOTO_VERSION_LOOKUP: dict[VersionSize, str] = {
    AssetVersionSize.ORIGINAL: "resOriginal",
    AssetVersionSize.ALTERNATIVE: "resOriginalAlt",
    AssetVersionSize.MEDIUM: "resJPEGMed",
    AssetVersionSize.THUMB: "resJPEGThumb",
    AssetVersionSize.ADJUSTED: "resJPEGFull",
    LivePhotoVersionSize.ORIGINAL: "resOriginalVidCompl",
    LivePhotoVersionSize.MEDIUM: "resVidMed",
    LivePhotoVersionSize.THUMB: "resVidSmall",
}

VIDEO_VERSION_LOOKUP: dict[VersionSize, str] = {
    AssetVersionSize.ORIGINAL: "resOriginal",
    AssetVersionSize.MEDIUM: "resVidMed",
    AssetVersionSize.THUMB: "resVidSmall",
}
ITEM_TYPES = {
    "public.heic": AssetItemType.IMAGE,
    "public.jpeg": AssetItemType.IMAGE,
    "public.png": AssetItemType.IMAGE,
    "com.apple.quicktime-movie": AssetItemType.MOVIE,
    "com.adobe.raw-image": AssetItemType.IMAGE,
    "com.canon.cr2-raw-image": AssetItemType.IMAGE,
    "com.canon.crw-raw-image": AssetItemType.IMAGE,
    "com.sony.arw-raw-image": AssetItemType.IMAGE,
    "com.fuji.raw-image": AssetItemType.IMAGE,
    "com.panasonic.rw2-raw-image": AssetItemType.IMAGE,
    "com.nikon.nrw-raw-image": AssetItemType.IMAGE,
    "com.pentax.raw-image": AssetItemType.IMAGE,
    "com.nikon.raw-image": AssetItemType.IMAGE,
    "com.olympus.raw-image": AssetItemType.IMAGE,
    "com.canon.cr3-raw-image": AssetItemType.IMAGE,
    "com.olympus.or-raw-image": AssetItemType.IMAGE,
}
ITEM_TYPE_EXTENSIONS = {
    "public.heic": "HEIC",
    "public.jpeg": "JPG",
    "public.png": "PNG",
    "com.apple.quicktime-movie": "MOV",
    "com.adobe.raw-image": "DNG",
    "com.canon.cr2-raw-image": "CR2",
    "com.canon.crw-raw-image": "CRW",
    "com.sony.arw-raw-image": "ARW",
    "com.fuji.raw-image": "RAF",
    "com.panasonic.rw2-raw-image": "RW2",
    "com.nikon.nrw-raw-image": "NRF",
    "com.pentax.raw-image": "PEF",
    "com.nikon.raw-image": "NEF",
    "com.olympus.raw-image": "ORF",
    "com.canon.cr3-raw-image": "CR3",
    "com.olympus.or-raw-image": "ORF",
}
VERSION_FILENAME_SUFFIX_LOOKUP: dict[VersionSize, str] = {
    AssetVersionSize.MEDIUM: "medium",
    AssetVersionSize.THUMB: "thumb",
    # LivePhotoVersionSize.MEDIUM: u"medium",
    # LivePhotoVersionSize.THUMB: u"thumb",
}
