# Copyright 2014 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Generated message classes for storage version v1.

Lets you store and retrieve potentially-large, immutable data objects.
"""

from gslib.third_party.protorpc import message_types
from gslib.third_party.protorpc import messages

from gslib.third_party.storage_apitools import encoding


package = 'storage'


class Bucket(messages.Message):
  """A bucket.

  Messages:
    CorsValueListEntry: A CorsValueListEntry object.
    LifecycleValue: The bucket's lifecycle configuration. See lifecycle
      management for more information.
    LoggingValue: The bucket's logging configuration, which defines the
      destination bucket and optional name prefix for the current bucket's
      logs.
    OwnerValue: The owner of the bucket. This is always the project team's
      owner group.
    VersioningValue: The bucket's versioning configuration.
    WebsiteValue: The bucket's website configuration.

  Fields:
    acl: Access controls on the bucket.
    cors: The bucket's Cross-Origin Resource Sharing (CORS) configuration.
    defaultObjectAcl: Default access controls to apply to new objects when no
      ACL is provided.
    etag: HTTP 1.1 Entity tag for the bucket.
    id: The ID of the bucket.
    kind: The kind of item this is. For buckets, this is always
      storage#bucket.
    lifecycle: The bucket's lifecycle configuration. See lifecycle management
      for more information.
    location: The location of the bucket. Object data for objects in the
      bucket resides in physical storage within this region. Defaults to US.
      See the developer's guide for the authoritative list.
    logging: The bucket's logging configuration, which defines the destination
      bucket and optional name prefix for the current bucket's logs.
    metageneration: The metadata generation of this bucket.
    name: The name of the bucket.
    owner: The owner of the bucket. This is always the project team's owner
      group.
    projectNumber: The project number of the project the bucket belongs to.
    selfLink: The URI of this bucket.
    storageClass: The bucket's storage class. This defines how objects in the
      bucket are stored and determines the SLA and the cost of storage.
      Typical values are STANDARD and DURABLE_REDUCED_AVAILABILITY. Defaults
      to STANDARD. See the developer's guide for the authoritative list.
    timeCreated: Creation time of the bucket in RFC 3339 format.
    versioning: The bucket's versioning configuration.
    website: The bucket's website configuration.
  """

  class CorsValueListEntry(messages.Message):
    """A CorsValueListEntry object.

    Fields:
      maxAgeSeconds: The value, in seconds, to return in the  Access-Control-
        Max-Age header used in preflight responses.
      method: The list of HTTP methods on which to include CORS response
        headers, (GET, OPTIONS, POST, etc) Note: "*" is permitted in the list
        of methods, and means "any method".
      origin: The list of Origins eligible to receive CORS response headers.
        Note: "*" is permitted in the list of origins, and means "any Origin".
      responseHeader: The list of HTTP headers other than the simple response
        headers to give permission for the user-agent to share across domains.
    """

    maxAgeSeconds = messages.IntegerField(1, variant=messages.Variant.INT32)
    method = messages.StringField(2, repeated=True)
    origin = messages.StringField(3, repeated=True)
    responseHeader = messages.StringField(4, repeated=True)

  class LifecycleValue(messages.Message):
    """The bucket's lifecycle configuration. See lifecycle management for more
    information.

    Messages:
      RuleValueListEntry: A RuleValueListEntry object.

    Fields:
      rule: A lifecycle management rule, which is made of an action to take
        and the condition(s) under which the action will be taken.
    """

    class RuleValueListEntry(messages.Message):
      """A RuleValueListEntry object.

      Messages:
        ActionValue: The action to take.
        ConditionValue: The condition(s) under which the action will be taken.

      Fields:
        action: The action to take.
        condition: The condition(s) under which the action will be taken.
      """

      class ActionValue(messages.Message):
        """The action to take.

        Fields:
          type: Type of the action. Currently, only Delete is supported.
        """

        type = messages.StringField(1)

      class ConditionValue(messages.Message):
        """The condition(s) under which the action will be taken.

        Fields:
          age: Age of an object (in days). This condition is satisfied when an
            object reaches the specified age.
          createdBefore: A date in RFC 3339 format with only the date part
            (for instance, "2013-01-15"). This condition is satisfied when an
            object is created before midnight of the specified date in UTC.
          isLive: Relevant only for versioned objects. If the value is true,
            this condition matches live objects; if the value is false, it
            matches archived objects.
          numNewerVersions: Relevant only for versioned objects. If the value
            is N, this condition is satisfied when there are at least N
            versions (including the live version) newer than this version of
            the object.
        """

        age = messages.IntegerField(1, variant=messages.Variant.INT32)
        createdBefore = message_types.DateTimeField(2)
        isLive = messages.BooleanField(3)
        numNewerVersions = messages.IntegerField(4, variant=messages.Variant.INT32)

      action = messages.MessageField('ActionValue', 1)
      condition = messages.MessageField('ConditionValue', 2)

    rule = messages.MessageField('RuleValueListEntry', 1, repeated=True)

  class LoggingValue(messages.Message):
    """The bucket's logging configuration, which defines the destination
    bucket and optional name prefix for the current bucket's logs.

    Fields:
      logBucket: The destination bucket where the current bucket's logs should
        be placed.
      logObjectPrefix: A prefix for log object names.
    """

    logBucket = messages.StringField(1)
    logObjectPrefix = messages.StringField(2)

  class OwnerValue(messages.Message):
    """The owner of the bucket. This is always the project team's owner group.

    Fields:
      entity: The entity, in the form project-owner-projectId.
      entityId: The ID for the entity.
    """

    entity = messages.StringField(1)
    entityId = messages.StringField(2)

  class VersioningValue(messages.Message):
    """The bucket's versioning configuration.

    Fields:
      enabled: While set to true, versioning is fully enabled for this bucket.
    """

    enabled = messages.BooleanField(1)

  class WebsiteValue(messages.Message):
    """The bucket's website configuration.

    Fields:
      mainPageSuffix: Behaves as the bucket's directory index where missing
        objects are treated as potential directories.
      notFoundPage: The custom object to return when a requested resource is
        not found.
    """

    mainPageSuffix = messages.StringField(1)
    notFoundPage = messages.StringField(2)

  acl = messages.MessageField('BucketAccessControl', 1, repeated=True)
  cors = messages.MessageField('CorsValueListEntry', 2, repeated=True)
  defaultObjectAcl = messages.MessageField('ObjectAccessControl', 3, repeated=True)
  etag = messages.StringField(4)
  id = messages.StringField(5)
  kind = messages.StringField(6, default=u'storage#bucket')
  lifecycle = messages.MessageField('LifecycleValue', 7)
  location = messages.StringField(8)
  logging = messages.MessageField('LoggingValue', 9)
  metageneration = messages.IntegerField(10)
  name = messages.StringField(11)
  owner = messages.MessageField('OwnerValue', 12)
  projectNumber = messages.IntegerField(13, variant=messages.Variant.UINT64)
  selfLink = messages.StringField(14)
  storageClass = messages.StringField(15)
  timeCreated = message_types.DateTimeField(16)
  versioning = messages.MessageField('VersioningValue', 17)
  website = messages.MessageField('WebsiteValue', 18)


class BucketAccessControl(messages.Message):
  """An access-control entry.

  Messages:
    ProjectTeamValue: The project team associated with the entity, if any.

  Fields:
    bucket: The name of the bucket.
    domain: The domain associated with the entity, if any.
    email: The email address associated with the entity, if any.
    entity: The entity holding the permission, in one of the following forms:
      - user-userId  - user-email  - group-groupId  - group-email  - domain-
      domain  - project-team-projectId  - allUsers  - allAuthenticatedUsers
      Examples:  - The user liz@example.com would be user-liz@example.com.  -
      The group example@googlegroups.com would be group-
      example@googlegroups.com.  - To refer to all members of the Google Apps
      for Business domain example.com, the entity would be domain-example.com.
    entityId: The ID for the entity, if any.
    etag: HTTP 1.1 Entity tag for the access-control entry.
    id: The ID of the access-control entry.
    kind: The kind of item this is. For bucket access control entries, this is
      always storage#bucketAccessControl.
    projectTeam: The project team associated with the entity, if any.
    role: The access permission for the entity. Can be READER, WRITER, or
      OWNER.
    selfLink: The link to this access-control entry.
  """

  class ProjectTeamValue(messages.Message):
    """The project team associated with the entity, if any.

    Fields:
      projectNumber: The project number.
      team: The team. Can be owners, editors, or viewers.
    """

    projectNumber = messages.StringField(1)
    team = messages.StringField(2)

  bucket = messages.StringField(1)
  domain = messages.StringField(2)
  email = messages.StringField(3)
  entity = messages.StringField(4)
  entityId = messages.StringField(5)
  etag = messages.StringField(6)
  id = messages.StringField(7)
  kind = messages.StringField(8, default=u'storage#bucketAccessControl')
  projectTeam = messages.MessageField('ProjectTeamValue', 9)
  role = messages.StringField(10)
  selfLink = messages.StringField(11)


class BucketAccessControls(messages.Message):
  """An access-control list.

  Fields:
    items: The list of items.
    kind: The kind of item this is. For lists of bucket access control
      entries, this is always storage#bucketAccessControls.
  """

  items = messages.MessageField('BucketAccessControl', 1, repeated=True)
  kind = messages.StringField(2, default=u'storage#bucketAccessControls')


class Buckets(messages.Message):
  """A list of buckets.

  Fields:
    items: The list of items.
    kind: The kind of item this is. For lists of buckets, this is always
      storage#buckets.
    nextPageToken: The continuation token, used to page through large result
      sets. Provide this value in a subsequent request to return the next page
      of results.
  """

  items = messages.MessageField('Bucket', 1, repeated=True)
  kind = messages.StringField(2, default=u'storage#buckets')
  nextPageToken = messages.StringField(3)


class Channel(messages.Message):
  """An notification channel used to watch for resource changes.

  Messages:
    ParamsValue: Additional parameters controlling delivery channel behavior.
      Optional.

  Fields:
    address: The address where notifications are delivered for this channel.
    expiration: Date and time of notification channel expiration, expressed as
      a Unix timestamp, in milliseconds. Optional.
    id: A UUID or similar unique string that identifies this channel.
    kind: Identifies this as a notification channel used to watch for changes
      to a resource. Value: the fixed string "api#channel".
    params: Additional parameters controlling delivery channel behavior.
      Optional.
    payload: A Boolean value to indicate whether payload is wanted. Optional.
    resourceId: An opaque ID that identifies the resource being watched on
      this channel. Stable across different API versions.
    resourceUri: A version-specific identifier for the watched resource.
    token: An arbitrary string delivered to the target address with each
      notification delivered over this channel. Optional.
    type: The type of delivery mechanism used for this channel.
  """

  @encoding.MapUnrecognizedFields('additionalProperties')
  class ParamsValue(messages.Message):
    """Additional parameters controlling delivery channel behavior. Optional.

    Messages:
      AdditionalProperty: An additional property for a ParamsValue object.

    Fields:
      additionalProperties: Declares a new parameter by name.
    """

    class AdditionalProperty(messages.Message):
      """An additional property for a ParamsValue object.

      Fields:
        key: Name of the additional property.
        value: A string attribute.
      """

      key = messages.StringField(1)
      value = messages.StringField(2)

    additionalProperties = messages.MessageField('AdditionalProperty', 1, repeated=True)

  address = messages.StringField(1)
  expiration = messages.IntegerField(2)
  id = messages.StringField(3)
  kind = messages.StringField(4, default=u'api#channel')
  params = messages.MessageField('ParamsValue', 5)
  payload = messages.BooleanField(6)
  resourceId = messages.StringField(7)
  resourceUri = messages.StringField(8)
  token = messages.StringField(9)
  type = messages.StringField(10)


class ComposeRequest(messages.Message):
  """A Compose request.

  Messages:
    SourceObjectsValueListEntry: A SourceObjectsValueListEntry object.

  Fields:
    destination: Properties of the resulting object.
    kind: The kind of item this is.
    sourceObjects: The list of source objects that will be concatenated into a
      single object.
  """

  class SourceObjectsValueListEntry(messages.Message):
    """A SourceObjectsValueListEntry object.

    Messages:
      ObjectPreconditionsValue: Conditions that must be met for this operation
        to execute.

    Fields:
      generation: The generation of this object to use as the source.
      name: The source object's name. The source object's bucket is implicitly
        the destination bucket.
      objectPreconditions: Conditions that must be met for this operation to
        execute.
    """

    class ObjectPreconditionsValue(messages.Message):
      """Conditions that must be met for this operation to execute.

      Fields:
        ifGenerationMatch: Only perform the composition if the generation of
          the source object that would be used matches this value. If this
          value and a generation are both specified, they must be the same
          value or the call will fail.
      """

      ifGenerationMatch = messages.IntegerField(1)

    generation = messages.IntegerField(1)
    name = messages.StringField(2)
    objectPreconditions = messages.MessageField('ObjectPreconditionsValue', 3)

  destination = messages.MessageField('Object', 1)
  kind = messages.StringField(2, default=u'storage#composeRequest')
  sourceObjects = messages.MessageField('SourceObjectsValueListEntry', 3, repeated=True)


class Object(messages.Message):
  """An object.

  Messages:
    MetadataValue: User-provided metadata, in key/value pairs.
    OwnerValue: The owner of the object. This will always be the uploader of
      the object.

  Fields:
    acl: Access controls on the object.
    bucket: The name of the bucket containing this object.
    cacheControl: Cache-Control directive for the object data.
    componentCount: Number of underlying components that make up this object.
      Components are accumulated by compose operations.
    contentDisposition: Content-Disposition of the object data.
    contentEncoding: Content-Encoding of the object data.
    contentLanguage: Content-Language of the object data.
    contentType: Content-Type of the object data.
    crc32c: CRC32c checksum, as described in RFC 4960, Appendix B; encoded
      using base64.
    etag: HTTP 1.1 Entity tag for the object.
    generation: The content generation of this object. Used for object
      versioning.
    id: The ID of the object.
    kind: The kind of item this is. For objects, this is always
      storage#object.
    md5Hash: MD5 hash of the data; encoded using base64.
    mediaLink: Media download link.
    metadata: User-provided metadata, in key/value pairs.
    metageneration: The version of the metadata for this object at this
      generation. Used for preconditions and for detecting changes in
      metadata. A metageneration number is only meaningful in the context of a
      particular generation of a particular object.
    name: The name of this object. Required if not specified by URL parameter.
    owner: The owner of the object. This will always be the uploader of the
      object.
    selfLink: The link to this object.
    size: Content-Length of the data in bytes.
    storageClass: Storage class of the object.
    timeDeleted: Deletion time of the object in RFC 3339 format. Will be
      returned if and only if this version of the object has been deleted.
    updated: Modification time of the object metadata in RFC 3339 format.
  """

  @encoding.MapUnrecognizedFields('additionalProperties')
  class MetadataValue(messages.Message):
    """User-provided metadata, in key/value pairs.

    Messages:
      AdditionalProperty: An additional property for a MetadataValue object.

    Fields:
      additionalProperties: An individual metadata entry.
    """

    class AdditionalProperty(messages.Message):
      """An additional property for a MetadataValue object.

      Fields:
        key: Name of the additional property.
        value: A string attribute.
      """

      key = messages.StringField(1)
      value = messages.StringField(2)

    additionalProperties = messages.MessageField('AdditionalProperty', 1, repeated=True)

  class OwnerValue(messages.Message):
    """The owner of the object. This will always be the uploader of the
    object.

    Fields:
      entity: The entity, in the form user-userId.
      entityId: The ID for the entity.
    """

    entity = messages.StringField(1)
    entityId = messages.StringField(2)

  acl = messages.MessageField('ObjectAccessControl', 1, repeated=True)
  bucket = messages.StringField(2)
  cacheControl = messages.StringField(3)
  componentCount = messages.IntegerField(4, variant=messages.Variant.INT32)
  contentDisposition = messages.StringField(5)
  contentEncoding = messages.StringField(6)
  contentLanguage = messages.StringField(7)
  contentType = messages.StringField(8)
  crc32c = messages.StringField(9)
  etag = messages.StringField(10)
  generation = messages.IntegerField(11)
  id = messages.StringField(12)
  kind = messages.StringField(13, default=u'storage#object')
  md5Hash = messages.StringField(14)
  mediaLink = messages.StringField(15)
  metadata = messages.MessageField('MetadataValue', 16)
  metageneration = messages.IntegerField(17)
  name = messages.StringField(18)
  owner = messages.MessageField('OwnerValue', 19)
  selfLink = messages.StringField(20)
  size = messages.IntegerField(21, variant=messages.Variant.UINT64)
  storageClass = messages.StringField(22)
  timeDeleted = message_types.DateTimeField(23)
  updated = message_types.DateTimeField(24)


class ObjectAccessControl(messages.Message):
  """An access-control entry.

  Messages:
    ProjectTeamValue: The project team associated with the entity, if any.

  Fields:
    bucket: The name of the bucket.
    domain: The domain associated with the entity, if any.
    email: The email address associated with the entity, if any.
    entity: The entity holding the permission, in one of the following forms:
      - user-userId  - user-email  - group-groupId  - group-email  - domain-
      domain  - project-team-projectId  - allUsers  - allAuthenticatedUsers
      Examples:  - The user liz@example.com would be user-liz@example.com.  -
      The group example@googlegroups.com would be group-
      example@googlegroups.com.  - To refer to all members of the Google Apps
      for Business domain example.com, the entity would be domain-example.com.
    entityId: The ID for the entity, if any.
    etag: HTTP 1.1 Entity tag for the access-control entry.
    generation: The content generation of the object.
    id: The ID of the access-control entry.
    kind: The kind of item this is. For object access control entries, this is
      always storage#objectAccessControl.
    object: The name of the object.
    projectTeam: The project team associated with the entity, if any.
    role: The access permission for the entity. Can be READER or OWNER.
    selfLink: The link to this access-control entry.
  """

  class ProjectTeamValue(messages.Message):
    """The project team associated with the entity, if any.

    Fields:
      projectNumber: The project number.
      team: The team. Can be owners, editors, or viewers.
    """

    projectNumber = messages.StringField(1)
    team = messages.StringField(2)

  bucket = messages.StringField(1)
  domain = messages.StringField(2)
  email = messages.StringField(3)
  entity = messages.StringField(4)
  entityId = messages.StringField(5)
  etag = messages.StringField(6)
  generation = messages.IntegerField(7)
  id = messages.StringField(8)
  kind = messages.StringField(9, default=u'storage#objectAccessControl')
  object = messages.StringField(10)
  projectTeam = messages.MessageField('ProjectTeamValue', 11)
  role = messages.StringField(12)
  selfLink = messages.StringField(13)


class ObjectAccessControls(messages.Message):
  """An access-control list.

  Fields:
    items: The list of items.
    kind: The kind of item this is. For lists of object access control
      entries, this is always storage#objectAccessControls.
  """

  items = messages.MessageField('extra_types.JsonValue', 1, repeated=True)
  kind = messages.StringField(2, default=u'storage#objectAccessControls')


class Objects(messages.Message):
  """A list of objects.

  Fields:
    items: The list of items.
    kind: The kind of item this is. For lists of objects, this is always
      storage#objects.
    nextPageToken: The continuation token, used to page through large result
      sets. Provide this value in a subsequent request to return the next page
      of results.
    prefixes: The list of prefixes of objects matching-but-not-listed up to
      and including the requested delimiter.
  """

  items = messages.MessageField('Object', 1, repeated=True)
  kind = messages.StringField(2, default=u'storage#objects')
  nextPageToken = messages.StringField(3)
  prefixes = messages.StringField(4, repeated=True)


class StandardQueryParameters(messages.Message):
  """Query parameters accepted by all methods.

  Enums:
    AltValueValuesEnum: Data format for the response.

  Fields:
    alt: Data format for the response.
    fields: Selector specifying which fields to include in a partial response.
    key: API key. Your API key identifies your project and provides you with
      API access, quota, and reports. Required unless you provide an OAuth 2.0
      token.
    oauth_token: OAuth 2.0 token for the current user.
    prettyPrint: Returns response with indentations and line breaks.
    quotaUser: Available to use for quota purposes for server-side
      applications. Can be any arbitrary string assigned to a user, but should
      not exceed 40 characters. Overrides userIp if both are provided.
    trace: A tracing token of the form "token:<tokenid>" or "email:<ldap>" to
      include in api requests.
    userIp: IP address of the site where the request originates. Use this if
      you want to enforce per-user limits.
  """

  class AltValueValuesEnum(messages.Enum):
    """Data format for the response.

    Values:
      json: Responses with Content-Type of application/json
    """
    json = 0

  alt = messages.EnumField('AltValueValuesEnum', 1, default=u'json')
  fields = messages.StringField(2)
  key = messages.StringField(3)
  oauth_token = messages.StringField(4)
  prettyPrint = messages.BooleanField(5, default=True)
  quotaUser = messages.StringField(6)
  trace = messages.StringField(7)
  userIp = messages.StringField(8)


class StorageBucketAccessControlsDeleteRequest(messages.Message):
  """A StorageBucketAccessControlsDeleteRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)


class StorageBucketAccessControlsDeleteResponse(messages.Message):
  """An empty StorageBucketAccessControlsDelete response."""


class StorageBucketAccessControlsGetRequest(messages.Message):
  """A StorageBucketAccessControlsGetRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)


class StorageBucketAccessControlsListRequest(messages.Message):
  """A StorageBucketAccessControlsListRequest object.

  Fields:
    bucket: Name of a bucket.
  """

  bucket = messages.StringField(1, required=True)


class StorageBucketsDeleteRequest(messages.Message):
  """A StorageBucketsDeleteRequest object.

  Fields:
    bucket: Name of a bucket.
    ifMetagenerationMatch: If set, only deletes the bucket if its
      metageneration matches this value.
    ifMetagenerationNotMatch: If set, only deletes the bucket if its
      metageneration does not match this value.
  """

  bucket = messages.StringField(1, required=True)
  ifMetagenerationMatch = messages.IntegerField(2)
  ifMetagenerationNotMatch = messages.IntegerField(3)


class StorageBucketsDeleteResponse(messages.Message):
  """An empty StorageBucketsDelete response."""


class StorageBucketsGetRequest(messages.Message):
  """A StorageBucketsGetRequest object.

  Enums:
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl.

  Fields:
    bucket: Name of a bucket.
    ifMetagenerationMatch: Makes the return of the bucket metadata conditional
      on whether the bucket's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the return of the bucket metadata
      conditional on whether the bucket's current metageneration does not
      match the given value.
    projection: Set of properties to return. Defaults to noAcl.
  """

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl.

    Values:
      full: Include all properties.
      noAcl: Omit acl and defaultObjectAcl properties.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  ifMetagenerationMatch = messages.IntegerField(2)
  ifMetagenerationNotMatch = messages.IntegerField(3)
  projection = messages.EnumField('ProjectionValueValuesEnum', 4)


class StorageBucketsInsertRequest(messages.Message):
  """A StorageBucketsInsertRequest object.

  Enums:
    PredefinedAclValueValuesEnum: Apply a predefined set of access controls to
      this bucket.
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl,
      unless the bucket resource specifies acl or defaultObjectAcl properties,
      when it defaults to full.

  Fields:
    bucket: A Bucket resource to be passed as the request body.
    predefinedAcl: Apply a predefined set of access controls to this bucket.
    project: A valid API project identifier.
    projection: Set of properties to return. Defaults to noAcl, unless the
      bucket resource specifies acl or defaultObjectAcl properties, when it
      defaults to full.
  """

  class PredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to this bucket.

    Values:
      authenticatedRead: Project team owners get OWNER access, and
        allAuthenticatedUsers get READER access.
      private: Project team owners get OWNER access.
      projectPrivate: Project team members get access according to their
        roles.
      publicRead: Project team owners get OWNER access, and allUsers get
        READER access.
      publicReadWrite: Project team owners get OWNER access, and allUsers get
        WRITER access.
    """
    authenticatedRead = 0
    private = 1
    projectPrivate = 2
    publicRead = 3
    publicReadWrite = 4

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl, unless the bucket
    resource specifies acl or defaultObjectAcl properties, when it defaults to
    full.

    Values:
      full: Include all properties.
      noAcl: Omit acl and defaultObjectAcl properties.
    """
    full = 0
    noAcl = 1

  bucket = messages.MessageField('Bucket', 1)
  predefinedAcl = messages.EnumField('PredefinedAclValueValuesEnum', 2)
  project = messages.StringField(3, required=True)
  projection = messages.EnumField('ProjectionValueValuesEnum', 4)


class StorageBucketsListRequest(messages.Message):
  """A StorageBucketsListRequest object.

  Enums:
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl.

  Fields:
    maxResults: Maximum number of buckets to return.
    pageToken: A previously-returned page token representing part of the
      larger set of results to view.
    project: A valid API project identifier.
    projection: Set of properties to return. Defaults to noAcl.
  """

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl.

    Values:
      full: Include all properties.
      noAcl: Omit acl and defaultObjectAcl properties.
    """
    full = 0
    noAcl = 1

  maxResults = messages.IntegerField(1, variant=messages.Variant.UINT32)
  pageToken = messages.StringField(2)
  project = messages.StringField(3, required=True)
  projection = messages.EnumField('ProjectionValueValuesEnum', 4)


class StorageBucketsPatchRequest(messages.Message):
  """A StorageBucketsPatchRequest object.

  Enums:
    PredefinedAclValueValuesEnum: Apply a predefined set of access controls to
      this bucket.
    ProjectionValueValuesEnum: Set of properties to return. Defaults to full.

  Fields:
    bucket: Name of a bucket.
    bucketResource: A Bucket resource to be passed as the request body.
    ifMetagenerationMatch: Makes the return of the bucket metadata conditional
      on whether the bucket's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the return of the bucket metadata
      conditional on whether the bucket's current metageneration does not
      match the given value.
    predefinedAcl: Apply a predefined set of access controls to this bucket.
    projection: Set of properties to return. Defaults to full.
  """

  class PredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to this bucket.

    Values:
      authenticatedRead: Project team owners get OWNER access, and
        allAuthenticatedUsers get READER access.
      private: Project team owners get OWNER access.
      projectPrivate: Project team members get access according to their
        roles.
      publicRead: Project team owners get OWNER access, and allUsers get
        READER access.
      publicReadWrite: Project team owners get OWNER access, and allUsers get
        WRITER access.
    """
    authenticatedRead = 0
    private = 1
    projectPrivate = 2
    publicRead = 3
    publicReadWrite = 4

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to full.

    Values:
      full: Include all properties.
      noAcl: Omit acl and defaultObjectAcl properties.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  bucketResource = messages.MessageField('Bucket', 2)
  ifMetagenerationMatch = messages.IntegerField(3)
  ifMetagenerationNotMatch = messages.IntegerField(4)
  predefinedAcl = messages.EnumField('PredefinedAclValueValuesEnum', 5)
  projection = messages.EnumField('ProjectionValueValuesEnum', 6)


class StorageBucketsUpdateRequest(messages.Message):
  """A StorageBucketsUpdateRequest object.

  Enums:
    PredefinedAclValueValuesEnum: Apply a predefined set of access controls to
      this bucket.
    ProjectionValueValuesEnum: Set of properties to return. Defaults to full.

  Fields:
    bucket: Name of a bucket.
    bucketResource: A Bucket resource to be passed as the request body.
    ifMetagenerationMatch: Makes the return of the bucket metadata conditional
      on whether the bucket's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the return of the bucket metadata
      conditional on whether the bucket's current metageneration does not
      match the given value.
    predefinedAcl: Apply a predefined set of access controls to this bucket.
    projection: Set of properties to return. Defaults to full.
  """

  class PredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to this bucket.

    Values:
      authenticatedRead: Project team owners get OWNER access, and
        allAuthenticatedUsers get READER access.
      private: Project team owners get OWNER access.
      projectPrivate: Project team members get access according to their
        roles.
      publicRead: Project team owners get OWNER access, and allUsers get
        READER access.
      publicReadWrite: Project team owners get OWNER access, and allUsers get
        WRITER access.
    """
    authenticatedRead = 0
    private = 1
    projectPrivate = 2
    publicRead = 3
    publicReadWrite = 4

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to full.

    Values:
      full: Include all properties.
      noAcl: Omit acl and defaultObjectAcl properties.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  bucketResource = messages.MessageField('Bucket', 2)
  ifMetagenerationMatch = messages.IntegerField(3)
  ifMetagenerationNotMatch = messages.IntegerField(4)
  predefinedAcl = messages.EnumField('PredefinedAclValueValuesEnum', 5)
  projection = messages.EnumField('ProjectionValueValuesEnum', 6)


class StorageChannelsStopResponse(messages.Message):
  """An empty StorageChannelsStop response."""


class StorageDefaultObjectAccessControlsDeleteRequest(messages.Message):
  """A StorageDefaultObjectAccessControlsDeleteRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)


class StorageDefaultObjectAccessControlsDeleteResponse(messages.Message):
  """An empty StorageDefaultObjectAccessControlsDelete response."""


class StorageDefaultObjectAccessControlsGetRequest(messages.Message):
  """A StorageDefaultObjectAccessControlsGetRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)


class StorageDefaultObjectAccessControlsListRequest(messages.Message):
  """A StorageDefaultObjectAccessControlsListRequest object.

  Fields:
    bucket: Name of a bucket.
    ifMetagenerationMatch: If present, only return default ACL listing if the
      bucket's current metageneration matches this value.
    ifMetagenerationNotMatch: If present, only return default ACL listing if
      the bucket's current metageneration does not match the given value.
  """

  bucket = messages.StringField(1, required=True)
  ifMetagenerationMatch = messages.IntegerField(2)
  ifMetagenerationNotMatch = messages.IntegerField(3)


class StorageObjectAccessControlsDeleteRequest(messages.Message):
  """A StorageObjectAccessControlsDeleteRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    object: Name of the object.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)
  generation = messages.IntegerField(3)
  object = messages.StringField(4, required=True)


class StorageObjectAccessControlsDeleteResponse(messages.Message):
  """An empty StorageObjectAccessControlsDelete response."""


class StorageObjectAccessControlsGetRequest(messages.Message):
  """A StorageObjectAccessControlsGetRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    object: Name of the object.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)
  generation = messages.IntegerField(3)
  object = messages.StringField(4, required=True)


class StorageObjectAccessControlsInsertRequest(messages.Message):
  """A StorageObjectAccessControlsInsertRequest object.

  Fields:
    bucket: Name of a bucket.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    object: Name of the object.
    objectAccessControl: A ObjectAccessControl resource to be passed as the
      request body.
  """

  bucket = messages.StringField(1, required=True)
  generation = messages.IntegerField(2)
  object = messages.StringField(3, required=True)
  objectAccessControl = messages.MessageField('ObjectAccessControl', 4)


class StorageObjectAccessControlsListRequest(messages.Message):
  """A StorageObjectAccessControlsListRequest object.

  Fields:
    bucket: Name of a bucket.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    object: Name of the object.
  """

  bucket = messages.StringField(1, required=True)
  generation = messages.IntegerField(2)
  object = messages.StringField(3, required=True)


class StorageObjectAccessControlsPatchRequest(messages.Message):
  """A StorageObjectAccessControlsPatchRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    object: Name of the object.
    objectAccessControl: A ObjectAccessControl resource to be passed as the
      request body.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)
  generation = messages.IntegerField(3)
  object = messages.StringField(4, required=True)
  objectAccessControl = messages.MessageField('ObjectAccessControl', 5)


class StorageObjectAccessControlsUpdateRequest(messages.Message):
  """A StorageObjectAccessControlsUpdateRequest object.

  Fields:
    bucket: Name of a bucket.
    entity: The entity holding the permission. Can be user-userId, user-
      emailAddress, group-groupId, group-emailAddress, allUsers, or
      allAuthenticatedUsers.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    object: Name of the object.
    objectAccessControl: A ObjectAccessControl resource to be passed as the
      request body.
  """

  bucket = messages.StringField(1, required=True)
  entity = messages.StringField(2, required=True)
  generation = messages.IntegerField(3)
  object = messages.StringField(4, required=True)
  objectAccessControl = messages.MessageField('ObjectAccessControl', 5)


class StorageObjectsComposeRequest(messages.Message):
  """A StorageObjectsComposeRequest object.

  Enums:
    DestinationPredefinedAclValueValuesEnum: Apply a predefined set of access
      controls to the destination object.

  Fields:
    composeRequest: A ComposeRequest resource to be passed as the request
      body.
    destinationBucket: Name of the bucket in which to store the new object.
    destinationObject: Name of the new object.
    destinationPredefinedAcl: Apply a predefined set of access controls to the
      destination object.
    ifGenerationMatch: Makes the operation conditional on whether the object's
      current generation matches the given value.
    ifMetagenerationMatch: Makes the operation conditional on whether the
      object's current metageneration matches the given value.
  """

  class DestinationPredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to the destination object.

    Values:
      authenticatedRead: Object owner gets OWNER access, and
        allAuthenticatedUsers get READER access.
      bucketOwnerFullControl: Object owner gets OWNER access, and project team
        owners get OWNER access.
      bucketOwnerRead: Object owner gets OWNER access, and project team owners
        get READER access.
      private: Object owner gets OWNER access.
      projectPrivate: Object owner gets OWNER access, and project team members
        get access according to their roles.
      publicRead: Object owner gets OWNER access, and allUsers get READER
        access.
    """
    authenticatedRead = 0
    bucketOwnerFullControl = 1
    bucketOwnerRead = 2
    private = 3
    projectPrivate = 4
    publicRead = 5

  composeRequest = messages.MessageField('ComposeRequest', 1)
  destinationBucket = messages.StringField(2, required=True)
  destinationObject = messages.StringField(3, required=True)
  destinationPredefinedAcl = messages.EnumField('DestinationPredefinedAclValueValuesEnum', 4)
  ifGenerationMatch = messages.IntegerField(5)
  ifMetagenerationMatch = messages.IntegerField(6)


class StorageObjectsCopyRequest(messages.Message):
  """A StorageObjectsCopyRequest object.

  Enums:
    DestinationPredefinedAclValueValuesEnum: Apply a predefined set of access
      controls to the destination object.
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl,
      unless the object resource specifies the acl property, when it defaults
      to full.

  Fields:
    destinationBucket: Name of the bucket in which to store the new object.
      Overrides the provided object metadata's bucket value, if any.
    destinationObject: Name of the new object. Required when the object
      metadata is not otherwise provided. Overrides the object metadata's name
      value, if any.
    destinationPredefinedAcl: Apply a predefined set of access controls to the
      destination object.
    ifGenerationMatch: Makes the operation conditional on whether the
      destination object's current generation matches the given value.
    ifGenerationNotMatch: Makes the operation conditional on whether the
      destination object's current generation does not match the given value.
    ifMetagenerationMatch: Makes the operation conditional on whether the
      destination object's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the operation conditional on whether the
      destination object's current metageneration does not match the given
      value.
    ifSourceGenerationMatch: Makes the operation conditional on whether the
      source object's generation matches the given value.
    ifSourceGenerationNotMatch: Makes the operation conditional on whether the
      source object's generation does not match the given value.
    ifSourceMetagenerationMatch: Makes the operation conditional on whether
      the source object's current metageneration matches the given value.
    ifSourceMetagenerationNotMatch: Makes the operation conditional on whether
      the source object's current metageneration does not match the given
      value.
    object: A Object resource to be passed as the request body.
    projection: Set of properties to return. Defaults to noAcl, unless the
      object resource specifies the acl property, when it defaults to full.
    sourceBucket: Name of the bucket in which to find the source object.
    sourceGeneration: If present, selects a specific revision of the source
      object (as opposed to the latest version, the default).
    sourceObject: Name of the source object.
  """

  class DestinationPredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to the destination object.

    Values:
      authenticatedRead: Object owner gets OWNER access, and
        allAuthenticatedUsers get READER access.
      bucketOwnerFullControl: Object owner gets OWNER access, and project team
        owners get OWNER access.
      bucketOwnerRead: Object owner gets OWNER access, and project team owners
        get READER access.
      private: Object owner gets OWNER access.
      projectPrivate: Object owner gets OWNER access, and project team members
        get access according to their roles.
      publicRead: Object owner gets OWNER access, and allUsers get READER
        access.
    """
    authenticatedRead = 0
    bucketOwnerFullControl = 1
    bucketOwnerRead = 2
    private = 3
    projectPrivate = 4
    publicRead = 5

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl, unless the object
    resource specifies the acl property, when it defaults to full.

    Values:
      full: Include all properties.
      noAcl: Omit the acl property.
    """
    full = 0
    noAcl = 1

  destinationBucket = messages.StringField(1, required=True)
  destinationObject = messages.StringField(2, required=True)
  destinationPredefinedAcl = messages.EnumField('DestinationPredefinedAclValueValuesEnum', 3)
  ifGenerationMatch = messages.IntegerField(4)
  ifGenerationNotMatch = messages.IntegerField(5)
  ifMetagenerationMatch = messages.IntegerField(6)
  ifMetagenerationNotMatch = messages.IntegerField(7)
  ifSourceGenerationMatch = messages.IntegerField(8)
  ifSourceGenerationNotMatch = messages.IntegerField(9)
  ifSourceMetagenerationMatch = messages.IntegerField(10)
  ifSourceMetagenerationNotMatch = messages.IntegerField(11)
  object = messages.MessageField('Object', 12)
  projection = messages.EnumField('ProjectionValueValuesEnum', 13)
  sourceBucket = messages.StringField(14, required=True)
  sourceGeneration = messages.IntegerField(15)
  sourceObject = messages.StringField(16, required=True)


class StorageObjectsDeleteRequest(messages.Message):
  """A StorageObjectsDeleteRequest object.

  Fields:
    bucket: Name of the bucket in which the object resides.
    generation: If present, permanently deletes a specific revision of this
      object (as opposed to the latest version, the default).
    ifGenerationMatch: Makes the operation conditional on whether the object's
      current generation matches the given value.
    ifGenerationNotMatch: Makes the operation conditional on whether the
      object's current generation does not match the given value.
    ifMetagenerationMatch: Makes the operation conditional on whether the
      object's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the operation conditional on whether the
      object's current metageneration does not match the given value.
    object: Name of the object.
  """

  bucket = messages.StringField(1, required=True)
  generation = messages.IntegerField(2)
  ifGenerationMatch = messages.IntegerField(3)
  ifGenerationNotMatch = messages.IntegerField(4)
  ifMetagenerationMatch = messages.IntegerField(5)
  ifMetagenerationNotMatch = messages.IntegerField(6)
  object = messages.StringField(7, required=True)


class StorageObjectsDeleteResponse(messages.Message):
  """An empty StorageObjectsDelete response."""


class StorageObjectsGetRequest(messages.Message):
  """A StorageObjectsGetRequest object.

  Enums:
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl.

  Fields:
    bucket: Name of the bucket in which the object resides.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    ifGenerationMatch: Makes the operation conditional on whether the object's
      generation matches the given value.
    ifGenerationNotMatch: Makes the operation conditional on whether the
      object's generation does not match the given value.
    ifMetagenerationMatch: Makes the operation conditional on whether the
      object's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the operation conditional on whether the
      object's current metageneration does not match the given value.
    object: Name of the object.
    projection: Set of properties to return. Defaults to noAcl.
  """

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl.

    Values:
      full: Include all properties.
      noAcl: Omit the acl property.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  generation = messages.IntegerField(2)
  ifGenerationMatch = messages.IntegerField(3)
  ifGenerationNotMatch = messages.IntegerField(4)
  ifMetagenerationMatch = messages.IntegerField(5)
  ifMetagenerationNotMatch = messages.IntegerField(6)
  object = messages.StringField(7, required=True)
  projection = messages.EnumField('ProjectionValueValuesEnum', 8)


class StorageObjectsInsertRequest(messages.Message):
  """A StorageObjectsInsertRequest object.

  Enums:
    PredefinedAclValueValuesEnum: Apply a predefined set of access controls to
      this object.
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl,
      unless the object resource specifies the acl property, when it defaults
      to full.

  Fields:
    bucket: Name of the bucket in which to store the new object. Overrides the
      provided object metadata's bucket value, if any.
    contentEncoding: If set, sets the contentEncoding property of the final
      object to this value. Setting this parameter is equivalent to setting
      the contentEncoding metadata property. This can be useful when uploading
      an object with uploadType=media to indicate the encoding of the content
      being uploaded.
    ifGenerationMatch: Makes the operation conditional on whether the object's
      current generation matches the given value.
    ifGenerationNotMatch: Makes the operation conditional on whether the
      object's current generation does not match the given value.
    ifMetagenerationMatch: Makes the operation conditional on whether the
      object's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the operation conditional on whether the
      object's current metageneration does not match the given value.
    name: Name of the object. Required when the object metadata is not
      otherwise provided. Overrides the object metadata's name value, if any.
    object: A Object resource to be passed as the request body.
    predefinedAcl: Apply a predefined set of access controls to this object.
    projection: Set of properties to return. Defaults to noAcl, unless the
      object resource specifies the acl property, when it defaults to full.
  """

  class PredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to this object.

    Values:
      authenticatedRead: Object owner gets OWNER access, and
        allAuthenticatedUsers get READER access.
      bucketOwnerFullControl: Object owner gets OWNER access, and project team
        owners get OWNER access.
      bucketOwnerRead: Object owner gets OWNER access, and project team owners
        get READER access.
      private: Object owner gets OWNER access.
      projectPrivate: Object owner gets OWNER access, and project team members
        get access according to their roles.
      publicRead: Object owner gets OWNER access, and allUsers get READER
        access.
    """
    authenticatedRead = 0
    bucketOwnerFullControl = 1
    bucketOwnerRead = 2
    private = 3
    projectPrivate = 4
    publicRead = 5

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl, unless the object
    resource specifies the acl property, when it defaults to full.

    Values:
      full: Include all properties.
      noAcl: Omit the acl property.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  contentEncoding = messages.StringField(2)
  ifGenerationMatch = messages.IntegerField(3)
  ifGenerationNotMatch = messages.IntegerField(4)
  ifMetagenerationMatch = messages.IntegerField(5)
  ifMetagenerationNotMatch = messages.IntegerField(6)
  name = messages.StringField(7)
  object = messages.MessageField('Object', 8)
  predefinedAcl = messages.EnumField('PredefinedAclValueValuesEnum', 9)
  projection = messages.EnumField('ProjectionValueValuesEnum', 10)


class StorageObjectsListRequest(messages.Message):
  """A StorageObjectsListRequest object.

  Enums:
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl.

  Fields:
    bucket: Name of the bucket in which to look for objects.
    delimiter: Returns results in a directory-like mode. items will contain
      only objects whose names, aside from the prefix, do not contain
      delimiter. Objects whose names, aside from the prefix, contain delimiter
      will have their name, truncated after the delimiter, returned in
      prefixes. Duplicate prefixes are omitted.
    maxResults: Maximum number of items plus prefixes to return. As duplicate
      prefixes are omitted, fewer total results may be returned than
      requested.
    pageToken: A previously-returned page token representing part of the
      larger set of results to view.
    prefix: Filter results to objects whose names begin with this prefix.
    projection: Set of properties to return. Defaults to noAcl.
    versions: If true, lists all versions of a file as distinct results.
  """

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl.

    Values:
      full: Include all properties.
      noAcl: Omit the acl property.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  delimiter = messages.StringField(2)
  maxResults = messages.IntegerField(3, variant=messages.Variant.UINT32)
  pageToken = messages.StringField(4)
  prefix = messages.StringField(5)
  projection = messages.EnumField('ProjectionValueValuesEnum', 6)
  versions = messages.BooleanField(7)


class StorageObjectsPatchRequest(messages.Message):
  """A StorageObjectsPatchRequest object.

  Enums:
    PredefinedAclValueValuesEnum: Apply a predefined set of access controls to
      this object.
    ProjectionValueValuesEnum: Set of properties to return. Defaults to full.

  Fields:
    bucket: Name of the bucket in which the object resides.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    ifGenerationMatch: Makes the operation conditional on whether the object's
      current generation matches the given value.
    ifGenerationNotMatch: Makes the operation conditional on whether the
      object's current generation does not match the given value.
    ifMetagenerationMatch: Makes the operation conditional on whether the
      object's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the operation conditional on whether the
      object's current metageneration does not match the given value.
    object: Name of the object.
    objectResource: A Object resource to be passed as the request body.
    predefinedAcl: Apply a predefined set of access controls to this object.
    projection: Set of properties to return. Defaults to full.
  """

  class PredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to this object.

    Values:
      authenticatedRead: Object owner gets OWNER access, and
        allAuthenticatedUsers get READER access.
      bucketOwnerFullControl: Object owner gets OWNER access, and project team
        owners get OWNER access.
      bucketOwnerRead: Object owner gets OWNER access, and project team owners
        get READER access.
      private: Object owner gets OWNER access.
      projectPrivate: Object owner gets OWNER access, and project team members
        get access according to their roles.
      publicRead: Object owner gets OWNER access, and allUsers get READER
        access.
    """
    authenticatedRead = 0
    bucketOwnerFullControl = 1
    bucketOwnerRead = 2
    private = 3
    projectPrivate = 4
    publicRead = 5

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to full.

    Values:
      full: Include all properties.
      noAcl: Omit the acl property.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  generation = messages.IntegerField(2)
  ifGenerationMatch = messages.IntegerField(3)
  ifGenerationNotMatch = messages.IntegerField(4)
  ifMetagenerationMatch = messages.IntegerField(5)
  ifMetagenerationNotMatch = messages.IntegerField(6)
  object = messages.StringField(7, required=True)
  objectResource = messages.MessageField('Object', 8)
  predefinedAcl = messages.EnumField('PredefinedAclValueValuesEnum', 9)
  projection = messages.EnumField('ProjectionValueValuesEnum', 10)


class StorageObjectsUpdateRequest(messages.Message):
  """A StorageObjectsUpdateRequest object.

  Enums:
    PredefinedAclValueValuesEnum: Apply a predefined set of access controls to
      this object.
    ProjectionValueValuesEnum: Set of properties to return. Defaults to full.

  Fields:
    bucket: Name of the bucket in which the object resides.
    generation: If present, selects a specific revision of this object (as
      opposed to the latest version, the default).
    ifGenerationMatch: Makes the operation conditional on whether the object's
      current generation matches the given value.
    ifGenerationNotMatch: Makes the operation conditional on whether the
      object's current generation does not match the given value.
    ifMetagenerationMatch: Makes the operation conditional on whether the
      object's current metageneration matches the given value.
    ifMetagenerationNotMatch: Makes the operation conditional on whether the
      object's current metageneration does not match the given value.
    object: Name of the object.
    objectResource: A Object resource to be passed as the request body.
    predefinedAcl: Apply a predefined set of access controls to this object.
    projection: Set of properties to return. Defaults to full.
  """

  class PredefinedAclValueValuesEnum(messages.Enum):
    """Apply a predefined set of access controls to this object.

    Values:
      authenticatedRead: Object owner gets OWNER access, and
        allAuthenticatedUsers get READER access.
      bucketOwnerFullControl: Object owner gets OWNER access, and project team
        owners get OWNER access.
      bucketOwnerRead: Object owner gets OWNER access, and project team owners
        get READER access.
      private: Object owner gets OWNER access.
      projectPrivate: Object owner gets OWNER access, and project team members
        get access according to their roles.
      publicRead: Object owner gets OWNER access, and allUsers get READER
        access.
    """
    authenticatedRead = 0
    bucketOwnerFullControl = 1
    bucketOwnerRead = 2
    private = 3
    projectPrivate = 4
    publicRead = 5

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to full.

    Values:
      full: Include all properties.
      noAcl: Omit the acl property.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  generation = messages.IntegerField(2)
  ifGenerationMatch = messages.IntegerField(3)
  ifGenerationNotMatch = messages.IntegerField(4)
  ifMetagenerationMatch = messages.IntegerField(5)
  ifMetagenerationNotMatch = messages.IntegerField(6)
  object = messages.StringField(7, required=True)
  objectResource = messages.MessageField('Object', 8)
  predefinedAcl = messages.EnumField('PredefinedAclValueValuesEnum', 9)
  projection = messages.EnumField('ProjectionValueValuesEnum', 10)


class StorageObjectsWatchAllRequest(messages.Message):
  """A StorageObjectsWatchAllRequest object.

  Enums:
    ProjectionValueValuesEnum: Set of properties to return. Defaults to noAcl.

  Fields:
    bucket: Name of the bucket in which to look for objects.
    channel: A Channel resource to be passed as the request body.
    delimiter: Returns results in a directory-like mode. items will contain
      only objects whose names, aside from the prefix, do not contain
      delimiter. Objects whose names, aside from the prefix, contain delimiter
      will have their name, truncated after the delimiter, returned in
      prefixes. Duplicate prefixes are omitted.
    maxResults: Maximum number of items plus prefixes to return. As duplicate
      prefixes are omitted, fewer total results may be returned than
      requested.
    pageToken: A previously-returned page token representing part of the
      larger set of results to view.
    prefix: Filter results to objects whose names begin with this prefix.
    projection: Set of properties to return. Defaults to noAcl.
    versions: If true, lists all versions of a file as distinct results.
  """

  class ProjectionValueValuesEnum(messages.Enum):
    """Set of properties to return. Defaults to noAcl.

    Values:
      full: Include all properties.
      noAcl: Omit the acl property.
    """
    full = 0
    noAcl = 1

  bucket = messages.StringField(1, required=True)
  channel = messages.MessageField('Channel', 2)
  delimiter = messages.StringField(3)
  maxResults = messages.IntegerField(4, variant=messages.Variant.UINT32)
  pageToken = messages.StringField(5)
  prefix = messages.StringField(6)
  projection = messages.EnumField('ProjectionValueValuesEnum', 7)
  versions = messages.BooleanField(8)


