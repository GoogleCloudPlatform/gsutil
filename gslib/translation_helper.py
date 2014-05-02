"""Utility module for translating XML API objects to/from JSON objects."""

import datetime
import json
import re
import textwrap
import xml.etree.ElementTree

import boto
from boto.gs.acl import ACL
from boto.gs.acl import ALL_AUTHENTICATED_USERS
from boto.gs.acl import ALL_USERS
from boto.gs.acl import Entries
from boto.gs.acl import Entry
from boto.gs.acl import GROUP_BY_DOMAIN
from boto.gs.acl import GROUP_BY_EMAIL
from boto.gs.acl import GROUP_BY_ID
from boto.gs.acl import USER_BY_EMAIL
from boto.gs.acl import USER_BY_ID
from third_party.storage_apitools import encoding as encoding
from third_party.storage_apitools import storage_v1_messages as apitools_messages

from gslib.cloud_api import ArgumentException
from gslib.cloud_api import NotFoundException
from gslib.cloud_api import Preconditions
from gslib.exception import CommandException

# In Python 2.6, ElementTree raises ExpatError instead of ParseError.
# pylint: disable=g-import-not-at-top
try:
  from xml.etree.ElementTree import ParseError as XmlParseError
except ImportError:
  from xml.parsers.expat import ExpatError as XmlParseError

CACHE_CONTROL_REGEX = re.compile(r'^cache-control', re.I)
CONTENT_DISPOSITION_REGEX = re.compile(r'^content-disposition', re.I)
CONTENT_ENCODING_REGEX = re.compile(r'^content-encoding', re.I)
CONTENT_LANGUAGE_REGEX = re.compile(r'^content-language', re.I)
CONTENT_MD5_REGEX = re.compile(r'^content-md5', re.I)
CONTENT_TYPE_REGEX = re.compile(r'^content-type', re.I)
GOOG_API_VERSION_REGEX = re.compile(r'^x-goog-api-version', re.I)
GOOG_GENERATION_MATCH_REGEX = re.compile(r'^x-goog-if-generation-match', re.I)
GOOG_METAGENERATION_MATCH_REGEX = re.compile(
    r'^x-goog-if-metageneration-match', re.I)
CUSTOM_GOOG_METADATA_REGEX = re.compile(r'^x-goog-meta-(?P<header_key>.*)',
                                        re.I)
CUSTOM_AMZ_METADATA_REGEX = re.compile(r'^x-amz-meta-(?P<header_key>.*)', re.I)

# gsutil-specific GUIDs for marking special metadata for S3 compatibility.
S3_ACL_MARKER_GUID = '3b89a6b5-b55a-4900-8c44-0b0a2f5eab43-s3-AclMarker'
S3_DELETE_MARKER_GUID = 'eadeeee8-fa8c-49bb-8a7d-0362215932d8-s3-DeleteMarker'
S3_MARKER_GUIDS = [S3_ACL_MARKER_GUID, S3_DELETE_MARKER_GUID]

DEFAULT_CONTENT_TYPE = 'application/octet-stream'

# Because CORS is just a list in apitools, we need special handling or blank
# CORS lists will get sent with other configuration commands such as lifecycle,
# commands, which would cause CORS configuration to be unintentionally removed.
# Protorpc defaults list values to an empty list, and won't allow us to set the
# value to None like other configuration fields, so there is no way to
# distinguish the default value from when we actually want to remove the CORS
# configuration.  To work around this, we create a dummy CORS entry that
# signifies that we should nullify the CORS configuration.
# A value of [] means don't modify the CORS configuration.
# A value of REMOVE_CORS_CONFIG means remove the CORS configuration.
REMOVE_CORS_CONFIG = [apitools_messages.Bucket.CorsValueListEntry(
    maxAgeSeconds=-1, method=['REMOVE_CORS_CONFIG'])]


def ObjectMetadataFromHeaders(headers):
  """Creates object metadata according to the provided headers.

  gsutil -h allows specifiying various headers (originally intended
  to be passed to boto in gsutil v3).  For the JSON API to be compatible with
  this option, we need to parse these headers into gsutil_api Object fields.

  Args:
    headers: Dict of headers passed via gsutil -h

  Raises:
    ArgumentException if an invalid header is encountered.

  Returns:
    apitools Object with relevant fields populated from headers.
  """
  obj_metadata = apitools_messages.Object()
  for header, value in headers.items():
    if CACHE_CONTROL_REGEX.match(header):
      obj_metadata.cacheControl = value.strip()
    elif CONTENT_DISPOSITION_REGEX.match(header):
      obj_metadata.contentDisposition = value.strip()
    elif CONTENT_ENCODING_REGEX.match(header):
      obj_metadata.contentEncoding = value.strip()
    elif CONTENT_MD5_REGEX.match(header):
      obj_metadata.md5Hash = value.strip()
    elif CONTENT_LANGUAGE_REGEX.match(header):
      obj_metadata.contentLanguage = value.strip()
    elif CONTENT_TYPE_REGEX.match(header):
      if not value:
        obj_metadata.contentType = DEFAULT_CONTENT_TYPE
      else:
        obj_metadata.contentType = value.strip()
    elif GOOG_API_VERSION_REGEX.match(header):
      # API version is only relevant for XML, ignore and rely on the XML API
      # to add the appropriate version.
      continue
    elif GOOG_GENERATION_MATCH_REGEX.match(header):
      # Preconditions are handled elsewhere, but allow these headers through.
      continue
    elif GOOG_METAGENERATION_MATCH_REGEX.match(header):
      # Preconditions are handled elsewhere, but allow these headers through.
      continue
    else:
      custom_goog_metadata_match = CUSTOM_GOOG_METADATA_REGEX.match(header)
      custom_amz_metadata_match = CUSTOM_AMZ_METADATA_REGEX.match(header)
      header_key = None
      if custom_goog_metadata_match:
        header_key = custom_goog_metadata_match.group('header_key')
      elif custom_amz_metadata_match:
        header_key = custom_amz_metadata_match.group('header_key')
      if header_key:
        if header_key.lower() == 'x-goog-content-language':
          # Work around content-language being inserted into custom metadata.
          continue
        if not obj_metadata.metadata:
          obj_metadata.metadata = apitools_messages.Object.MetadataValue()
        if not obj_metadata.metadata.additionalProperties:
          obj_metadata.metadata.additionalProperties = []
        obj_metadata.metadata.additionalProperties.append(
            apitools_messages.Object.MetadataValue.AdditionalProperty(
                key=header_key, value=value))
      else:
        raise ArgumentException(
            'Invalid header specifed: %s:%s' % (header, value))
  return obj_metadata


def HeadersFromObjectMetadata(dst_obj_metadata, provider):
  """Creates a header dictionary based on existing object metadata.

  Args:
    dst_obj_metadata: Object metadata to create the headers from.
    provider: Provider string ('gs' or 's3')

  Returns:
    Headers dictionary.
  """
  headers = {}
  if not dst_obj_metadata:
    return
  # Metadata values of '' mean suppress/remove this header.
  if dst_obj_metadata.cacheControl is not None:
    if not dst_obj_metadata.cacheControl:
      headers['cache-control'] = None
    else:
      headers['cache-control'] = dst_obj_metadata.cacheControl.strip()
  if dst_obj_metadata.contentDisposition:
    if not dst_obj_metadata.contentDisposition:
      headers['content-disposition'] = None
    else:
      headers['content-disposition'] = (
          dst_obj_metadata.contentDisposition.strip())
  if dst_obj_metadata.contentEncoding:
    if not dst_obj_metadata.contentEncoding:
      headers['content-encoding'] = None
    else:
      headers['content-encoding'] = dst_obj_metadata.contentEncoding.strip()
  if dst_obj_metadata.contentLanguage:
    if not dst_obj_metadata.contentLanguage:
      headers['content-language'] = None
    else:
      headers['content-language'] = dst_obj_metadata.contentLanguage.strip()
  if dst_obj_metadata.md5Hash:
    if not dst_obj_metadata.md5Hash:
      headers['Content-MD5'] = None
    else:
      headers['Content-MD5'] = dst_obj_metadata.md5Hash.strip()
  if dst_obj_metadata.contentType is not None:
    if not dst_obj_metadata.contentType:
      headers['content-type'] = None
    else:
      headers['content-type'] = dst_obj_metadata.contentType.strip()
  if (dst_obj_metadata.metadata and
      dst_obj_metadata.metadata.additionalProperties):
    for additional_property in dst_obj_metadata.metadata.additionalProperties:
      # Work around content-language being inserted into custom metadata by
      # the XML API.
      if additional_property.key == 'content-language':
        continue
      # Don't translate special metadata markers.
      if additional_property.key in S3_MARKER_GUIDS:
        continue
      if provider == 'gs':
        header_name = 'x-goog-meta-' + additional_property.key
      elif provider == 's3':
        header_name = 'x-amz-meta-' + additional_property.key
      else:
        raise ArgumentException('Invalid provider specified: %s' % provider)
      if (additional_property.value is not None and
          not additional_property.value):
        headers[header_name] = None
      else:
        headers[header_name] = additional_property.value
  return headers


def CopyObjectMetadata(src_obj_metadata, dst_obj_metadata, override=False):
  """Copies metadata from src_obj_metadata to dst_obj_metadata.

  Args:
    src_obj_metadata: Metadata from source object
    dst_obj_metadata: Initialized metadata for destination object
    override: If true, will overwrite metadata in destination object.
              If false, only writes metadata for values that don't already
              exist.
  """
  if override or not dst_obj_metadata.cacheControl:
    dst_obj_metadata.cacheControl = src_obj_metadata.cacheControl
  if override or not dst_obj_metadata.contentDisposition:
    dst_obj_metadata.contentDisposition = src_obj_metadata.contentDisposition
  if override or not dst_obj_metadata.contentEncoding:
    dst_obj_metadata.contentEncoding = src_obj_metadata.contentEncoding
  if override or not dst_obj_metadata.contentLanguage:
    dst_obj_metadata.contentLanguage = src_obj_metadata.contentLanguage
  if override or not dst_obj_metadata.contentType:
    dst_obj_metadata.contentType = src_obj_metadata.contentType
  if override or not dst_obj_metadata.md5Hash:
    dst_obj_metadata.md5Hash = src_obj_metadata.md5Hash

  # TODO: Apitools should ideally treat metadata like a real dictionary instead
  # of a list of key/value pairs (with an O(N^2) lookup).  In practice the
  # number of values is typically small enough not to matter.
  # Work around this by creating our own dictionary.
  if (src_obj_metadata.metadata and
      src_obj_metadata.metadata.additionalProperties):
    if not dst_obj_metadata.metadata:
      dst_obj_metadata.metadata = apitools_messages.Object.MetadataValue()
    if not dst_obj_metadata.metadata.additionalProperties:
      dst_obj_metadata.metadata.additionalProperties = []
    dst_metadata_dict = {}
    for dst_prop in dst_obj_metadata.metadata.additionalProperties:
      dst_metadata_dict[dst_prop.key] = dst_prop.value
    for src_prop in src_obj_metadata.metadata.additionalProperties:
      if src_prop.key in dst_metadata_dict:
        if override:
          # Metadata values of '' mean suppress/remove this header.
          if src_prop.value is not None and not src_prop.value:
            dst_metadata_dict[src_prop.key] = None
          else:
            dst_metadata_dict[src_prop.key] = src_prop.value
      else:
        dst_metadata_dict[src_prop.key] = src_prop.value
    # Rewrite the list with our updated dict.
    dst_obj_metadata.metadata.additionalProperties = []
    for k, v in dst_metadata_dict.iteritems():
      dst_obj_metadata.metadata.additionalProperties.append(
          apitools_messages.Object.MetadataValue.AdditionalProperty(key=k,
                                                                    value=v))


def PreconditionsFromHeaders(headers):
  """Creates bucket or object preconditions acccording to the provided headers.

  Args:
    headers: Dict of headers passed via gsutil -h

  Returns:
    gsutil Cloud API Preconditions object fields populated from headers, or None
    if no precondition headers are present.
  """
  return_preconditions = Preconditions()
  try:
    for header, value in headers.items():
      if GOOG_GENERATION_MATCH_REGEX.match(header):
        return_preconditions.gen_match = long(value)
      if GOOG_METAGENERATION_MATCH_REGEX.match(header):
        return_preconditions.meta_gen_match = long(value)
  except ValueError, _:
    raise ArgumentException('Invalid precondition header specified. '
                            'x-goog-if-generation-match and '
                            'x-goog-if-metageneration match must be specified '
                            'with a positive integer value.')
  return return_preconditions


def CreateBucketNotFoundException(code, provider, bucket_name):
  return NotFoundException('%s://%s bucket does not exist.' %
                           (provider, bucket_name), status=code)


def CreateObjectNotFoundException(code, provider, bucket_name, object_name,
                                  generation=None):
  uri_string = '%s://%s/%s' % (provider, bucket_name, object_name)
  if generation:
    uri_string += '#%s' % str(generation)
  return NotFoundException('%s does not exist.' % uri_string, status=code)


def EncodeStringAsLong(string_to_convert):
  """Encodes an ASCII string as a python long.

  This is used for modeling S3 version_id's as apitools generation.  Because
  python longs can be arbitrarily large, this works.

  Args:
    string_to_convert: ASCII string to convert to a long.

  Returns:
    Long that represents the input string.
  """
  return long(string_to_convert.encode('hex'), 16)


def _DecodeLongAsString(long_to_convert):
  """Decodes an encoded python long into an ASCII string.

  This is used for modeling S3 version_id's as apitools generation.

  Args:
    long_to_convert: long to convert to ASCII string. If this is already a
                     string, it is simply returned.

  Returns:
    String decoded from the input long.
  """
  if isinstance(long_to_convert, basestring):
    # Already converted.
    return long_to_convert
  return hex(long_to_convert)[2:-1].decode('hex')


def GenerationFromUrlAndString(url, generation):
  """Decodes a generation from a StorageURL and a generation string.

  This is used to represent gs and s3 versioning.

  Args:
    url: StorageUrl representing the object.
    generation: Long or string representing the object's generation or
                version.

  Returns:
    Valid generation string for use in URLs.
  """
  if url.scheme == 's3' and generation:
    return _DecodeLongAsString(generation)
  return generation


def CheckForXmlConfigurationAndRaise(config_type_string, json_txt):
  """Checks a JSON parse exception for provided XML configuration."""
  try:
    xml.etree.ElementTree.fromstring(str(json_txt))
    raise ArgumentException('\n'.join(textwrap.wrap(
        'XML {0} data provided; Google Cloud Storage {0} configuration '
        'now uses JSON format. To convert your {0}, set the desired XML '
        'ACL using \'gsutil {1} set ...\' with gsutil version 3.x. Then '
        'use \'gsutil {1} get ...\' with gsutil version 4 or greater to '
        'get the corresponding JSON {0}.'.format(config_type_string,
                                                 config_type_string.lower()))))
  except XmlParseError:
    pass
  raise ArgumentException('JSON %s data could not be loaded '
                          'from: %s' % (config_type_string, json_txt))


class LifecycleTranslation(object):
  """Functions for converting between various lifecycle formats.

    This class handles conversation to and from Boto Cors objects, JSON text,
    and apitools Message objects.
  """

  @classmethod
  def BotoLifecycleFromMessage(cls, lifecycle_message):
    """Translates an apitools message to a boto lifecycle object."""
    boto_lifecycle = boto.gs.lifecycle.LifecycleConfig()
    if lifecycle_message:
      for rule_message in lifecycle_message.rule:
        boto_rule = boto.gs.lifecycle.Rule()
        if (rule_message.action and rule_message.action.type and
            rule_message.action.type.lower() == 'delete'):
          boto_rule.action = boto.gs.lifecycle.DELETE
        if rule_message.condition:
          if rule_message.condition.age:
            boto_rule.conditions[boto.gs.lifecycle.AGE] = (
                str(rule_message.condition.age))
          if rule_message.condition.createdBefore:
            boto_rule.conditions[boto.gs.lifecycle.CREATED_BEFORE] = (
                str(rule_message.condition.createdBefore))
          if rule_message.condition.isLive:
            boto_rule.conditions[boto.gs.lifecycle.IS_LIVE] = (
                str(rule_message.condition.isLive))
          if rule_message.condition.numNewerVersions:
            boto_rule.conditions[boto.gs.lifecycle.NUM_NEWER_VERSIONS] = (
                str(rule_message.condition.numNewerVersions))
        boto_lifecycle.append(boto_rule)
    return boto_lifecycle

  @classmethod
  def BotoLifecycleToMessage(cls, boto_lifecycle):
    """Translates a boto lifecycle object to an apitools message."""
    lifecycle_message = None
    if boto_lifecycle:
      lifecycle_message = apitools_messages.Bucket.LifecycleValue()
      for boto_rule in boto_lifecycle:
        lifecycle_rule = (
            apitools_messages.Bucket.LifecycleValue.RuleValueListEntry())
        lifecycle_rule.condition = (apitools_messages.Bucket.LifecycleValue.
                                    RuleValueListEntry.ConditionValue())
        if boto_rule.action and boto_rule.action == boto.gs.lifecycle.DELETE:
          lifecycle_rule.action = (apitools_messages.Bucket.LifecycleValue.
                                   RuleValueListEntry.ActionValue(
                                       type='Delete'))
        if boto.gs.lifecycle.AGE in boto_rule.conditions:
          lifecycle_rule.condition.age = int(
              boto_rule.conditions[boto.gs.lifecycle.AGE])
        if boto.gs.lifecycle.CREATED_BEFORE in boto_rule.conditions:
          lifecycle_rule.condition.createdBefore = (
              LifecycleTranslation.TranslateBotoLifecycleTimestamp(
                  boto_rule.conditions[boto.gs.lifecycle.CREATED_BEFORE]))
        if boto.gs.lifecycle.IS_LIVE in boto_rule.conditions:
          lifecycle_rule.condition.isLive = bool(
              boto_rule.conditions[boto.gs.lifecycle.IS_LIVE])
        if boto.gs.lifecycle.NUM_NEWER_VERSIONS in boto_rule.conditions:
          lifecycle_rule.condition.numNewerVersions = int(
              boto_rule.conditions[boto.gs.lifecycle.NUM_NEWER_VERSIONS])
        lifecycle_message.rule.append(lifecycle_rule)
    return lifecycle_message

  @classmethod
  def JsonLifecycleFromMessage(cls, lifecycle_message):
    """Translates an apitools message to lifecycle JSON."""
    return str(encoding.MessageToJson(lifecycle_message)) + '\n'

  @classmethod
  def JsonLifecycleToMessage(cls, json_txt):
    """Translates lifecycle JSON to an apitools message."""
    try:
      deserialized_lifecycle = json.loads(json_txt)
      lifecycle = encoding.DictToMessage(
          deserialized_lifecycle, apitools_messages.Bucket.LifecycleValue)
      return lifecycle
    except ValueError:
      CheckForXmlConfigurationAndRaise('lifecycle', json_txt)

  @classmethod
  def TranslateBotoLifecycleTimestamp(cls, lifecycle_datetime):
    """Parses the timestamp from the boto lifecycle into a datetime object."""
    fmt = '%Y-%m-%d'
    return datetime.datetime.strptime(lifecycle_datetime, fmt)


class CorsTranslation(object):
  """Functions for converting between various CORS formats.

    This class handles conversation to and from Boto Cors objects, JSON text,
    and apitools Message objects.
  """

  @classmethod
  def BotoCorsFromMessage(cls, cors_message):
    """Translates an apitools message to a boto Cors object."""
    cors = boto.gs.cors.Cors()
    cors.cors = []
    for collection_message in cors_message:
      collection_elements = []
      if collection_message.maxAgeSeconds:
        collection_elements.append((boto.gs.cors.MAXAGESEC,
                                    str(collection_message.maxAgeSeconds)))
      if collection_message.method:
        method_elements = []
        for method in collection_message.method:
          method_elements.append((boto.gs.cors.METHOD, method))
        collection_elements.append((boto.gs.cors.METHODS, method_elements))
      if collection_message.origin:
        origin_elements = []
        for origin in collection_message.origin:
          origin_elements.append((boto.gs.cors.ORIGIN, origin))
        collection_elements.append((boto.gs.cors.ORIGINS, origin_elements))
      if collection_message.responseHeader:
        header_elements = []
        for header in collection_message.responseHeader:
          header_elements.append((boto.gs.cors.HEADER, header))
        collection_elements.append((boto.gs.cors.HEADERS, header_elements))
      cors.cors.append(collection_elements)
    return cors

  @classmethod
  def BotoCorsToMessage(cls, boto_cors):
    """Translates a boto Cors object to an apitools message."""
    message_cors = []
    if boto_cors.cors:
      for cors_collection in boto_cors.cors:
        if cors_collection:
          collection_message = apitools_messages.Bucket.CorsValueListEntry()
          for element_tuple in cors_collection:
            if element_tuple[0] == boto.gs.cors.MAXAGESEC:
              collection_message.maxAgeSeconds = int(element_tuple[1])
            if element_tuple[0] == boto.gs.cors.METHODS:
              for method_tuple in element_tuple[1]:
                collection_message.method.append(method_tuple[1])
            if element_tuple[0] == boto.gs.cors.ORIGINS:
              for origin_tuple in element_tuple[1]:
                collection_message.origin.append(origin_tuple[1])
            if element_tuple[0] == boto.gs.cors.HEADERS:
              for header_tuple in element_tuple[1]:
                collection_message.responseHeader.append(header_tuple[1])
          message_cors.append(collection_message)
    return message_cors

  @classmethod
  def JsonCorsToMessageEntries(cls, json_cors):
    """Translates CORS JSON to an apitools message.

    Args:
      json_cors: JSON string representing CORS configuration.

    Returns:
      List of apitools Bucket.CorsValueListEntry. An empty list represents
      no CORS configuration.
    """
    try:
      deserialized_cors = json.loads(json_cors)
      cors = []
      for cors_entry in deserialized_cors:
        cors.append(encoding.DictToMessage(
            cors_entry, apitools_messages.Bucket.CorsValueListEntry))
      return cors
    except ValueError:
      CheckForXmlConfigurationAndRaise('CORS', json_cors)

  @classmethod
  def MessageEntriesToJson(cls, cors_message):
    """Translates an apitools message to CORS JSON."""
    json_text = ''
    # Because CORS is a MessageField, serialize/deserialize as JSON list.
    json_text += '['
    printed_one = False
    for cors_entry in cors_message:
      if printed_one:
        json_text += ','
      else:
        printed_one = True
      json_text += encoding.MessageToJson(cors_entry)
    json_text += ']\n'
    return json_text


def S3MarkerAclFromObjectMetadata(object_metadata):
  """Retrieves GUID-marked S3 ACL from object metadata, if present.

  Args:
    object_metadata: Object metadata to check.

  Returns:
    S3 ACL text, if present, None otherwise.
  """
  if (object_metadata and object_metadata.metadata and
      object_metadata.metadata.additionalProperties):
    for prop in object_metadata.metadata.additionalProperties:
      if prop.key == S3_ACL_MARKER_GUID:
        return prop.value


def AddS3MarkerAclToObjectMetadata(object_metadata, acl_text):
  """Adds a GUID-marked S3 ACL to the object metadata.

  Args:
    object_metadata: Object metadata to add the acl to.
    acl_text: S3 ACL text to add.
  """
  if not object_metadata.metadata:
    object_metadata.metadata = apitools_messages.Object.MetadataValue()
  if not object_metadata.metadata.additionalProperties:
    object_metadata.metadata.additionalProperties = []

  object_metadata.metadata.additionalProperties.append(
      apitools_messages.Object.MetadataValue.AdditionalProperty(
          key=S3_ACL_MARKER_GUID, value=acl_text))


class AclTranslation(object):
  """Functions for converting between various ACL formats.

    This class handles conversion to and from Boto ACL objects, JSON text,
    and apitools Message objects.
  """

  JSON_TO_XML_ROLES = {'READER': 'READ', 'WRITER': 'WRITE',
                       'OWNER': 'FULL_CONTROL'}
  XML_TO_JSON_ROLES = {'READ': 'READER', 'WRITE': 'WRITER',
                       'FULL_CONTROL': 'OWNER'}

  @classmethod
  def BotoAclFromJson(cls, acl_json):
    acl = ACL()
    acl.parent = None
    acl.entries = cls.BotoEntriesFromJson(acl_json, acl)
    return acl

  @classmethod
  # acl_message is a list of messages, either object or bucketaccesscontrol
  def BotoAclFromMessage(cls, acl_message):
    acl_dicts = []
    for message in acl_message:
      acl_dicts.append(encoding.MessageToDict(message))
    return cls.BotoAclFromJson(acl_dicts)

  @classmethod
  def BotoAclToJson(cls, acl):
    if hasattr(acl, 'entries'):
      return cls.BotoEntriesToJson(acl.entries)
    return []

  @classmethod
  def BotoObjectAclToMessage(cls, acl):
    for entry in cls.BotoAclToJson(acl):
      message = encoding.DictToMessage(entry,
                                       apitools_messages.ObjectAccessControl)
      message.kind = u'storage#objectAccessControl'
      yield message

  @classmethod
  def BotoBucketAclToMessage(cls, acl):
    for entry in cls.BotoAclToJson(acl):
      message = encoding.DictToMessage(entry,
                                       apitools_messages.BucketAccessControl)
      message.kind = u'storage#bucketAccessControl'
      yield message

  @classmethod
  def BotoEntriesFromJson(cls, acl_json, parent):
    entries = Entries(parent)
    entries.parent = parent
    entries.entry_list = [cls.BotoEntryFromJson(entry_json)
                          for entry_json in acl_json]
    return entries

  @classmethod
  def BotoEntriesToJson(cls, entries):
    return [cls.BotoEntryToJson(entry) for entry in entries.entry_list]

  @classmethod
  def BotoEntryFromJson(cls, entry_json):
    """Converts a JSON entry into a Boto ACL entry."""
    entity = entry_json['entity']
    permission = cls.JSON_TO_XML_ROLES[entry_json['role']]
    if entity.lower() == ALL_USERS.lower():
      return Entry(type=ALL_USERS, permission=permission)
    elif entity.lower() == ALL_AUTHENTICATED_USERS.lower():
      return Entry(type=ALL_AUTHENTICATED_USERS, permission=permission)
    elif 'email' in entry_json:
      if entity.startswith('user'):
        scope_type = USER_BY_EMAIL
      elif entity.startswith('group'):
        scope_type = GROUP_BY_EMAIL
      return Entry(type=scope_type, email_address=entry_json['email'],
                   permission=permission)
    elif 'entityId' in entry_json:
      if entity.startswith('user'):
        scope_type = USER_BY_ID
      elif entity.startswith('group'):
        scope_type = GROUP_BY_ID
      return Entry(type=scope_type, id=entry_json['entityId'],
                   permission=permission)
    elif 'domain' in entry_json:
      if entity.startswith('domain'):
        scope_type = GROUP_BY_DOMAIN
      return Entry(type=scope_type, domain=entry_json['domain'],
                   permission=permission)
    elif 'project' in entry_json:
      if entity.startswith('project'):
        raise CommandException('XML API does not support project scopes, '
                               'cannot translate ACL.')
    raise CommandException('Failed to translate JSON ACL to XML.')

  @classmethod
  def BotoEntryToJson(cls, entry):
    """Converts a Boto ACL entry to a valid JSON dictionary."""
    acl_entry_json = {}
    # JSON API documentation uses camel case.
    scope_type_lower = entry.scope.type.lower()
    if scope_type_lower == ALL_USERS.lower():
      acl_entry_json['entity'] = 'allUsers'
    elif scope_type_lower == ALL_AUTHENTICATED_USERS.lower():
      acl_entry_json['entity'] = 'allAuthenticatedUsers'
    elif scope_type_lower == USER_BY_EMAIL.lower():
      acl_entry_json['entity'] = 'user-%s' % entry.scope.email_address
      acl_entry_json['email'] = entry.scope.email_address
    elif scope_type_lower == USER_BY_ID.lower():
      acl_entry_json['entity'] = 'user-%s' % entry.scope.id
      acl_entry_json['entityId'] = entry.scope.id
    elif scope_type_lower == GROUP_BY_EMAIL.lower():
      acl_entry_json['entity'] = 'group-%s' % entry.scope.email_address
      acl_entry_json['email'] = entry.scope.email_address
    elif scope_type_lower == GROUP_BY_ID.lower():
      acl_entry_json['entity'] = 'group-%s' % entry.scope.id
      acl_entry_json['entityId'] = entry.scope.id
    elif scope_type_lower == GROUP_BY_DOMAIN.lower():
      acl_entry_json['entity'] = 'domain-%s' % entry.scope.domain
      acl_entry_json['domain'] = entry.scope.domain
    else:
      raise ArgumentException('ACL contains invalid scope type: %s' %
                              scope_type_lower)

    acl_entry_json['role'] = cls.XML_TO_JSON_ROLES[entry.permission]
    return acl_entry_json

  @classmethod
  def JsonToMessage(cls, json_data, message_type):
    """Converts the input JSON data into list of Object/BucketAccessControls.

    Args:
      json_data: String of JSON to convert.
      message_type: Which type of access control entries to return,
                    either ObjectAccessControl or BucketAccessControl.

    Raises:
      ArgumentException on invalid JSON data.

    Returns:
      List of ObjectAccessControl or BucketAccessControl elements.
    """
    try:
      deserialized_acl = json.loads(json_data)

      acl = []
      for acl_entry in deserialized_acl:
        acl.append(encoding.DictToMessage(acl_entry, message_type))
      return acl
    except ValueError:
      CheckForXmlConfigurationAndRaise('ACL', json_data)

  @classmethod
  def JsonFromMessage(cls, acl):
    """Strips unnecessary fields from an ACL message and returns valid JSON.

    Args:
      acl: iterable ObjectAccessControl or BucketAccessControl

    Returns:
      ACL JSON string.
    """
    serializable_acl = []
    if acl is not None:
      for acl_entry in acl:
        if acl_entry.kind == u'storage#objectAccessControl':
          acl_entry.object = None
          acl_entry.generation = None
        acl_entry.kind = None
        acl_entry.bucket = None
        acl_entry.id = None
        acl_entry.selfLink = None
        acl_entry.etag = None
        serializable_acl.append(encoding.MessageToDict(acl_entry))
    return json.dumps(serializable_acl, sort_keys=True,
                      indent=2, separators=(',', ': '))

