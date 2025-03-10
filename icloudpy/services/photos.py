"""Photo service."""

import base64
import dataclasses
import json
import logging
import os
import plistlib
import zlib
from collections.abc import Generator, Sequence
from datetime import datetime
from typing import Any, Optional, cast

# fmt: off
from urllib.parse import urlencode  # pylint: disable=bad-option-value,relative-import

import dateutil.tz
from pytz import UTC
from six import PY2

# fmt: on
from icloudpy.exceptions import ICloudPyServiceNotActivatedException
from icloudpy.photo_versions import (
    ITEM_TYPE_EXTENSIONS,
    ITEM_TYPES,
    PHOTO_VERSION_LOOKUP,
    VIDEO_VERSION_LOOKUP,
    AssetItemType,
    AssetVersion,
    AssetVersionSize,
    VersionSize,
)

LOGGER = logging.getLogger(__name__)


class PhotoLibrary:
    """Represents a library in the user"s photos.

    This provides access to all the albums as well as the photos.
    """

    SMART_FOLDERS = {
        "All Photos": {
            "obj_type": "CPLAssetByAssetDateWithoutHiddenOrDeleted",
            "list_type": "CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted",
            "direction": "ASCENDING",
            "query_filter": None,
        },
        "Time-lapse": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Timelapse",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "TIMELAPSE"},
                },
            ],
        },
        "Videos": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Video",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "VIDEO"},
                },
            ],
        },
        "Slo-mo": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Slomo",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "SLOMO"},
                },
            ],
        },
        "Bursts": {
            "obj_type": "CPLAssetBurstStackAssetByAssetDate",
            "list_type": "CPLBurstStackAssetAndMasterByAssetDate",
            "direction": "ASCENDING",
            "query_filter": None,
        },
        "Favorites": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Favorite",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "FAVORITE"},
                },
            ],
        },
        "Panoramas": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Panorama",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "PANORAMA"},
                },
            ],
        },
        "Screenshots": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Screenshot",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "SCREENSHOT"},
                },
            ],
        },
        "Live": {
            "obj_type": "CPLAssetInSmartAlbumByAssetDate:Live",
            "list_type": "CPLAssetAndMasterInSmartAlbumByAssetDate",
            "direction": "ASCENDING",
            "query_filter": [
                {
                    "fieldName": "smartAlbum",
                    "comparator": "EQUALS",
                    "fieldValue": {"type": "STRING", "value": "LIVE"},
                },
            ],
        },
        "Recently Deleted": {
            "obj_type": "CPLAssetDeletedByExpungedDate",
            "list_type": "CPLAssetAndMasterDeletedByExpungedDate",
            "direction": "ASCENDING",
            "query_filter": None,
        },
        "Hidden": {
            "obj_type": "CPLAssetHiddenByAssetDate",
            "list_type": "CPLAssetAndMasterHiddenByAssetDate",
            "direction": "ASCENDING",
            "query_filter": None,
        },
    }

    def __init__(self, service: "PhotosService", zone_id: dict[str, Any]):
        self.service = service
        self.zone_id = zone_id

        self._albums: Optional[dict[str, PhotoAlbum]] = None

        url = f"{self.service._service_endpoint}/records/query?{urlencode(self.service.params)}"
        json_data = json.dumps(
            {
                "query": {"recordType": "CheckIndexingState"},
                "zoneID": self.zone_id,
            },
        )

        request = self.service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )
        response = request.json()
        indexing_state = response["records"][0]["fields"]["state"]["value"]
        if indexing_state != "FINISHED":
            raise ICloudPyServiceNotActivatedException(
                ("iCloud Photo Library not finished indexing.  Please try again in a few minutes"),
                None,
            )

    @property
    def albums(self) -> dict[str, "PhotoAlbum"]:
        if not self._albums:
            self._albums = {
                name: PhotoAlbum(self.service, name, zone_id=self.zone_id, **props)
                for (name, props) in self.SMART_FOLDERS.items()
            }

            for folder in self._fetch_folders():
                if folder["recordName"] in (
                    "----Root-Folder----",
                    "----Project-Root-Folder----",
                ) or (folder["fields"].get("isDeleted") and folder["fields"]["isDeleted"]["value"]):
                    continue

                folder_id = folder["recordName"]
                folder_obj_type = f"CPLContainerRelationNotDeletedByAssetDate:{folder_id}"
                folder_name = base64.b64decode(
                    folder["fields"]["albumNameEnc"]["value"],
                ).decode("utf-8")
                query_filter = [
                    {
                        "fieldName": "parentId",
                        "comparator": "EQUALS",
                        "fieldValue": {"type": "STRING", "value": folder_id},
                    },
                ]

                album = PhotoAlbum(
                    self.service,
                    folder_name,
                    "CPLContainerRelationLiveByAssetDate",
                    folder_obj_type,
                    "ASCENDING",
                    query_filter,
                    folder_id=folder_id,
                    zone_id=self.zone_id,
                )
                self._albums[folder_name] = album

        return self._albums

    def _fetch_folders(self) -> Sequence[dict[str, Any]]:
        url = f"{self.service._service_endpoint}/records/query?{urlencode(self.service.params)}"
        json_data = json.dumps(
            {
                "query": {"recordType": "CPLAlbumByPositionLive"},
                "zoneID": self.zone_id,
            },
        )

        request = self.service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )
        response = request.json()

        return cast(Sequence[dict[str, Any]], response["records"])

    @property
    def all(self):
        return self.albums["All Photos"]


class PhotosService(PhotoLibrary):
    """The "Photos" iCloud service.

    This also acts as a way to access the user"s primary library.
    """

    def __init__(
        self,
        service_root: str,
        session,
        params: dict[str, Any],
    ):
        self.session = session
        self.params = dict(params)
        self._service_root = service_root
        self._service_endpoint = f"{self._service_root}/database/1/com.apple.photos.cloud/production/private"

        self._libraries: Optional[dict[str, PhotoLibrary]] = None

        self.params.update({"remapEnums": True, "getCurrentSyncToken": True})

        self._photo_assets = {}

        super().__init__(service=self, zone_id={"zoneName": "PrimarySync"})

    @property
    def libraries(self) -> dict[str, PhotoLibrary]:
        if not self._libraries:
            try:
                url = f"{self._service_endpoint}/zones/list"
                request = self.session.post(
                    url,
                    data="{}",
                    headers={"Content-type": "text/plain"},
                )
                response = request.json()
                zones = response["zones"]
            except Exception as e:
                LOGGER.error(f"library exception: {str(e)}")

            libraries = {}
            for zone in zones:
                if not zone.get("deleted"):
                    zone_name = zone["zoneID"]["zoneName"]
                    libraries[zone_name] = PhotoLibrary(self, zone_id=zone["zoneID"])
                    # obj_type="CPLAssetByAssetDateWithoutHiddenOrDeleted",
                    # list_type="CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted",
                    # direction="ASCENDING", query_filter=None,
                    # zone_id=zone["zoneID"])

            self._libraries = libraries

        return self._libraries


class PhotoAlbum:
    """A photo album."""

    def __init__(
        self,
        service,
        name,
        list_type,
        obj_type,
        direction,
        query_filter=None,
        page_size=100,
        folder_id=None,
        zone_id=None,
    ):
        self.name = name
        self.service = service
        self.list_type = list_type
        self.obj_type = obj_type
        self.direction = direction
        self.query_filter = query_filter
        self.page_size = page_size
        self.folder_id = folder_id

        if zone_id:
            self._zone_id: dict[str, Any] = zone_id
        else:
            self._zone_id = {"zoneName": "PrimarySync"}

        self._len = None

        self._subalbums = {}

    @property
    def title(self):
        """Gets the album name."""
        return self.name

    def __iter__(self):
        return self.photos

    def __len__(self):
        if self._len is None:
            url = f"{self.service._service_endpoint}/internal/records/query/batch?{urlencode(self.service.params)}"
            request = self.service.session.post(
                url,
                data=json.dumps(
                    {
                        "batch": [
                            {
                                "resultsLimit": 1,
                                "query": {
                                    "filterBy": {
                                        "fieldName": "indexCountID",
                                        "fieldValue": {
                                            "type": "STRING_LIST",
                                            "value": [self.obj_type],
                                        },
                                        "comparator": "IN",
                                    },
                                    "recordType": "HyperionIndexCountLookup",
                                },
                                "zoneWide": True,
                                "zoneID": {"zoneName": self._zone_id["zoneName"]},
                            },
                        ],
                    },
                ),
                headers={"Content-type": "text/plain"},
            )
            response = request.json()

            self._len = response["batch"][0]["records"][0]["fields"]["itemCount"]["value"]

        return self._len

    def _fetch_subalbums(self):
        url = (f"{self.service._service_endpoint}/records/query?") + urlencode(
            self.service.params,
        )
        # pylint: disable=consider-using-f-string
        query = """{{
                "query": {{
                    "recordType":"CPLAlbumByPositionLive",
                    "filterBy": [
                        {{
                            "fieldName": "parentId",
                            "comparator": "EQUALS",
                            "fieldValue": {{
                                "value": "{}",
                                "type": "STRING"
                            }}
                        }}
                    ]
                }},
                "zoneID": {{
                    "zoneName":"{}"
                }}
            }}""".format(
            self.folder_id,
            self._zone_id["zoneName"],
        )
        json_data = query
        request = self.service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )
        response = request.json()

        return response["records"]

    @property
    def subalbums(self):
        """Returns the subalbums"""
        if not self._subalbums and self.folder_id:
            for folder in self._fetch_subalbums():
                if folder["fields"].get("isDeleted") and folder["fields"]["isDeleted"]["value"]:
                    continue

                folder_id = folder["recordName"]
                folder_obj_type = f"CPLContainerRelationNotDeletedByAssetDate:{folder_id}"
                folder_name = base64.b64decode(
                    folder["fields"]["albumNameEnc"]["value"],
                ).decode("utf-8")
                query_filter = [
                    {
                        "fieldName": "parentId",
                        "comparator": "EQUALS",
                        "fieldValue": {"type": "STRING", "value": folder_id},
                    },
                ]

                album = PhotoAlbum(
                    self.service,
                    name=folder_name,
                    list_type="CPLContainerRelationLiveByAssetDate",
                    obj_type=folder_obj_type,
                    direction="ASCENDING",
                    query_filter=query_filter,
                    folder_id=folder_id,
                    zone_id=self._zone_id,
                )
                self._subalbums[folder_name] = album
        return self._subalbums

    @property
    def photos(self) -> Generator["PhotoAsset", Any, None]:
        """Returns the album photos."""
        if self.direction == "DESCENDING":
            offset = len(self) - 1
        else:
            offset = 0

        while True:
            url = (f"{self.service._service_endpoint}/records/query?") + urlencode(
                self.service.params,
            )
            request = self.service.session.post(
                url,
                data=json.dumps(
                    self._list_query_gen(
                        offset,
                        self.list_type,
                        self.direction,
                        self.query_filter,
                    ),
                ),
                headers={"Content-type": "text/plain"},
            )
            response = request.json()

            asset_records = {}
            master_records = []
            for rec in response["records"]:
                if rec["recordType"] == "CPLAsset":
                    master_id = rec["fields"]["masterRef"]["value"]["recordName"]
                    asset_records[master_id] = rec
                elif rec["recordType"] == "CPLMaster":
                    master_records.append(rec)

            master_records_len = len(master_records)
            if master_records_len:
                if self.direction == "DESCENDING":
                    offset = offset - master_records_len
                else:
                    offset = offset + master_records_len

                for master_record in master_records:
                    record_name = master_record["recordName"]
                    yield PhotoAsset(
                        self.service,
                        master_record,
                        asset_records[record_name],
                    )
            else:
                break

    def _list_query_gen(self, offset, list_type, direction, query_filter=None):
        query = {
            "query": {
                "filterBy": [
                    {
                        "fieldName": "startRank",
                        "fieldValue": {"type": "INT64", "value": offset},
                        "comparator": "EQUALS",
                    },
                    {
                        "fieldName": "direction",
                        "fieldValue": {"type": "STRING", "value": direction},
                        "comparator": "EQUALS",
                    },
                ],
                "recordType": list_type,
            },
            "resultsLimit": self.page_size * 2,
            "desiredKeys": [
                "resJPEGFullWidth",
                "resJPEGFullHeight",
                "resJPEGFullFileType",
                "resJPEGFullFingerprint",
                "resJPEGFullRes",
                "resJPEGLargeWidth",
                "resJPEGLargeHeight",
                "resJPEGLargeFileType",
                "resJPEGLargeFingerprint",
                "resJPEGLargeRes",
                "resJPEGMedWidth",
                "resJPEGMedHeight",
                "resJPEGMedFileType",
                "resJPEGMedFingerprint",
                "resJPEGMedRes",
                "resJPEGThumbWidth",
                "resJPEGThumbHeight",
                "resJPEGThumbFileType",
                "resJPEGThumbFingerprint",
                "resJPEGThumbRes",
                "resVidFullWidth",
                "resVidFullHeight",
                "resVidFullFileType",
                "resVidFullFingerprint",
                "resVidFullRes",
                "resVidMedWidth",
                "resVidMedHeight",
                "resVidMedFileType",
                "resVidMedFingerprint",
                "resVidMedRes",
                "resVidSmallWidth",
                "resVidSmallHeight",
                "resVidSmallFileType",
                "resVidSmallFingerprint",
                "resVidSmallRes",
                "resSidecarWidth",
                "resSidecarHeight",
                "resSidecarFileType",
                "resSidecarFingerprint",
                "resSidecarRes",
                "itemType",
                "dataClassType",
                "filenameEnc",
                "originalOrientation",
                "resOriginalWidth",
                "resOriginalHeight",
                "resOriginalFileType",
                "resOriginalFingerprint",
                "resOriginalRes",
                "resOriginalAltWidth",
                "resOriginalAltHeight",
                "resOriginalAltFileType",
                "resOriginalAltFingerprint",
                "resOriginalAltRes",
                "resOriginalVidComplWidth",
                "resOriginalVidComplHeight",
                "resOriginalVidComplFileType",
                "resOriginalVidComplFingerprint",
                "resOriginalVidComplRes",
                "isDeleted",
                "isExpunged",
                "dateExpunged",
                "remappedRef",
                "recordName",
                "recordType",
                "recordChangeTag",
                "masterRef",
                "adjustmentRenderType",
                "assetDate",
                "addedDate",
                "isFavorite",
                "isHidden",
                "orientation",
                "duration",
                "assetSubtype",
                "assetSubtypeV2",
                "assetHDRType",
                "burstFlags",
                "burstFlagsExt",
                "burstId",
                "captionEnc",
                "extendedDescEnc",
                "locationEnc",
                "locationV2Enc",
                "locationLatitude",
                "locationLongitude",
                "adjustmentType",
                "timeZoneOffset",
                "vidComplDurValue",
                "vidComplDurScale",
                "vidComplDispValue",
                "vidComplDispScale",
                "vidComplVisibilityState",
                "customRenderedValue",
                "containerId",
                "itemId",
                "position",
                "isKeyAsset",
                "importedByBundleIdentifierEnc",
                "importedByDisplayNameEnc",
                "importedBy",
                "keywordsEnc",
                "adjustedMediaMetaDataEnc",
                "adjustmentSimpleDataEnc",
            ],
            "zoneID": self._zone_id,
        }

        if query_filter:
            query["query"]["filterBy"].extend(query_filter)

        return query

    def __unicode__(self):
        return self.title

    def __str__(self):
        as_unicode = self.__unicode__()
        if PY2:
            return as_unicode.encode("utf-8", "ignore")
        return as_unicode

    def __repr__(self):
        return f"<{type(self).__name__}: '{self}'>"


@dataclasses.dataclass
class GpsData:
    gps_altitude: float | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_speed: float | None = None
    gps_timestamp: datetime | None = None


class PhotoAsset:
    """A photo."""

    def __init__(self, service: PhotosService, master_record: dict[str, Any], asset_record: dict[str, Any]) -> None:
        self._service = service
        self._master_record = master_record
        self._asset_record = asset_record

        self._versions: Optional[dict[VersionSize, AssetVersion]] = None
        self._title = None
        self._filename = None
        self._description = None
        self._adjustments = None
        self._keywords = None
        self._location = None
        self._asset_date = None

    @property
    def title(self):
        if self._title is None and "captionEnc" in self._asset_record["fields"]:
            self._title = base64.b64decode(self._asset_record["fields"]["captionEnc"]["value"]).decode("utf-8")

        return self._title

    @property
    def description(self):
        if self._description is None and "extendedDescEnc" in self._asset_record["fields"]:
            self._description = base64.b64decode(self._asset_record["fields"]["extendedDescEnc"]["value"]).decode(
                "utf-8"
            )

        return self._description

    @property
    def adjustments(self):
        # adjustementSimpleDataEnc can be one of three formats:
        # - a binary plist - starting with 'bplist00' ( YnBsaXN0MD once encoded), seemingly used for some videos
        #   metadata (slow motion range etc.)
        # - a CRDT (Conflict-free Replicated Data Types) - starting with 'crdt' (Y3JkdA once encoded) - used for
        #   drawings and annotations on photos and screenshots
        # - a zlib compressed JSON - used for simple photo metadata adjustments (orientation etc.)
        # for exporting metadata, we only consider the JSON data, but it's the only one that doesn't have a predictable
        # start pattern, so we check by excluding the other two
        if self._adjustments is None and (
            "adjustmentSimpleDataEnc" in self._asset_record["fields"]
            and not self._asset_record["fields"]["adjustmentSimpleDataEnc"]["value"].startswith("Y3JkdA")  # "crdt"
            and not self._asset_record["fields"]["adjustmentSimpleDataEnc"]["value"].startswith("YnBsaXN0MD")
        ):  # "bplist00"
            self._adjustments = json.loads(
                zlib.decompress(
                    base64.b64decode(self._asset_record["fields"]["adjustmentSimpleDataEnc"]["value"]),
                    -zlib.MAX_WBITS,
                )
            )

        return self._adjustments

    @property
    def keywords(self):
        if (
            self._keywords is None
            and "keywordsEnc" in self._asset_record["fields"]
            and len(self._asset_record["fields"]["keywordsEnc"]) > 0
        ):
            self._keywords = plistlib.loads(
                base64.b64decode(self._asset_record["fields"]["keywordsEnc"]["value"]),
            )

        return self._keywords

    @property
    def location(self):
        if self._location is None:
            self._location = GpsData()
            if "locationEnc" in self._asset_record["fields"]:
                location = plistlib.loads(
                    base64.b64decode(self._asset_record["fields"]["locationEnc"]["value"]),
                )
                self._location.gps_altitude = location.get("alt")
                self._location.gps_latitude = location.get("lat")
                self._location.gps_longitude = location.get("lon")
                self._location.gps_speed = location.get("speed")
                self._location.gps_timestamp = (
                    location.get("timestamp") if isinstance(location.get("timestamp"), datetime) else None
                )

        return self._location

    @property
    def is_hidden(self) -> bool:
        return "isHidden" in self._asset_record["fields"] and self._asset_record["fields"]["isHidden"]["value"] == 1

    @property
    def is_deleted(self) -> bool:
        return "isDeleted" in self._asset_record["fields"] and self._asset_record["fields"]["isDeleted"]["value"] == 1

    @property
    def is_favorite(self) -> bool:
        return "isFavorite" in self._asset_record["fields"] and self._asset_record["fields"]["isFavorite"]["value"] == 1

    @property
    def is_screenshot(self) -> bool:
        return (
            "assetSubtypeV2" in self._asset_record["fields"]
            and int(self._asset_record["fields"]["assetSubtypeV2"]["value"]) == 3
        )

    @property
    def id(self):
        """Gets the photo id."""
        return self._master_record["recordName"]

    @property
    def filename(self):
        """Gets the photo file name."""
        if not self._filename:
            self._filename = base64.b64decode(
                self._master_record["fields"]["filenameEnc"]["value"],
            ).decode("utf-8")

        return self._filename

    @property
    def size(self):
        """Gets the photo size."""
        return self._master_record["fields"]["resOriginalRes"]["value"]["size"]

    @property
    def created(self):
        """Gets the photo created date."""
        return self.asset_date

    @property
    def asset_date(self):
        """Gets the photo asset date."""
        if not self._asset_date:
            try:
                timezone_offset = 0
                if "timeZoneOffset" in self._asset_record["fields"]:
                    timezone_offset = self._asset_record["fields"]["timeZoneOffset"]["value"]
                self._asset_date = datetime.fromtimestamp(
                    self._asset_record["fields"]["assetDate"]["value"] / 1000.0,
                    tz=dateutil.tz.tzoffset(None, timezone_offset),
                )
            except KeyError:
                self._asset_date = datetime.fromtimestamp(0)

        return self._asset_date

    @property
    def added_date(self):
        """Gets the photo added date."""
        return datetime.fromtimestamp(
            self._asset_record["fields"]["addedDate"]["value"] / 1000.0,
            tz=UTC,
        )

    @property
    def dimensions(self):
        """Gets the photo dimensions."""
        return (
            self._master_record["fields"]["resOriginalWidth"]["value"],
            self._master_record["fields"]["resOriginalHeight"]["value"],
        )

    @property
    def item_type(self) -> Optional[AssetItemType]:
        fields = self._master_record["fields"]
        if "itemType" not in fields:
            # raise ValueError(f"Cannot find itemType in {fields!r}")
            return None
        item_type_field = fields["itemType"]
        if "value" not in item_type_field:
            # raise ValueError(f"Cannot find value in itemType {item_type_field!r}")
            return None
        item_type = item_type_field["value"]
        if item_type in ITEM_TYPES:
            return ITEM_TYPES[item_type]
        if self.filename.lower().endswith((".heic", ".png", ".jpg", ".jpeg")):
            return AssetItemType.IMAGE
        return AssetItemType.MOVIE

    @property
    def item_type_extension(self) -> str:
        fields = self._master_record["fields"]
        if "itemType" not in fields or "value" not in fields["itemType"]:
            return "unknown"
        item_type = self._master_record["fields"]["itemType"]["value"]
        if item_type in ITEM_TYPE_EXTENSIONS:
            return ITEM_TYPE_EXTENSIONS[item_type]
        return "unknown"

    @property
    def versions(self) -> dict[VersionSize, AssetVersion]:
        """Gets the photo versions."""
        if not self._versions:
            self._versions: dict[VersionSize, AssetVersion] = {}
            if self.item_type == AssetItemType.MOVIE:
                typed_version_lookup: dict[VersionSize, str] = VIDEO_VERSION_LOOKUP
            else:
                typed_version_lookup = PHOTO_VERSION_LOOKUP

            for key, prefix in typed_version_lookup.items():
                fields: dict[str, Any] | None = None
                if f"{prefix}Res" in self._asset_record["fields"]:
                    fields = self._asset_record["fields"]
                elif f"{prefix}Res" in self._master_record["fields"]:
                    fields = self._master_record["fields"]
                if fields:
                    version = AssetVersion(self.filename)

                    if width_entry := fields.get(f"{prefix}Width"):
                        version.width = width_entry["value"]

                    if height_entry := fields.get(f"{prefix}Height"):
                        version.height = height_entry["value"]

                    if size_entry := fields.get(f"{prefix}Res"):
                        version.size = size_entry["value"]["size"]
                        version.url = size_entry["value"]["downloadURL"]
                        version.checksum = size_entry["value"]["fileChecksum"]

                    if type_entry := fields.get(f"{prefix}FileType"):
                        version.type = type_entry["value"]

                    filename, extension = os.path.splitext(version.filename)
                    version.filename = filename + "." + ITEM_TYPE_EXTENSIONS.get(version.type, extension[1:])

                    self._versions[key] = version

        return self._versions

    def download(self, version: VersionSize = AssetVersionSize.ORIGINAL, **kwargs):
        """Returns the photo file."""
        if (version_obj := self.versions.get(version)) and version_obj.url:
            return self._service.session.get(
                version_obj.url,
                stream=True,
                **kwargs,
            )

        return None

    def delete(self):
        """Deletes the photo."""
        json_data = json.dumps(
            {
                "atomic": True,
                "desiredKeys": ["isDeleted"],
                "operations": [
                    {
                        "operationType": "update",
                        "record": {
                            "fields": {"isDeleted": {"value": 1}},
                            "recordChangeTag": self._asset_record["recordChangeTag"],
                            "recordName": self._asset_record["recordName"],
                            "recordType": self._asset_record["recordType"],
                        },
                    },
                ],
                "zoneID": self._service.zone_id,
            },
        )

        endpoint = self._service._service_endpoint
        params = urlencode(self._service.params)
        url = f"{endpoint}/records/modify?{params}"

        return self._service.session.post(
            url,
            data=json_data,
            headers={"Content-type": "text/plain"},
        )

    def __repr__(self):
        return f"<{type(self).__name__}: id={self.id}>"
