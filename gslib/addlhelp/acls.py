# Copyright 2012 Google Inc.
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

from gslib.help_provider import HELP_NAME
from gslib.help_provider import HELP_NAME_ALIASES
from gslib.help_provider import HELP_ONE_LINE_SUMMARY
from gslib.help_provider import HelpProvider
from gslib.help_provider import HELP_TEXT
from gslib.help_provider import HelpType
from gslib.help_provider import HELP_TYPE

_detailed_help_text = ("""
<B>OVERVIEW</B>
  Access Control Lists (ACLs) allow you to control who can read and write
  your data, and who can read and write the ACLs themselves.

  If not specified at the time an object is uploaded (e.g., via the gstil cp
  -a option), objects will be created with a default object ACL set on the
  bucket (see "gsutil help setdefacl"). You can change the ACL on an object
  or bucket using the gsutil setacl command (see "gsutil help setacl").


<B>BUCKET VS OBJECT ACLS</B>
  In Google Cloud Storage, the bucket ACL works as follows:

    - Users granted READ access are allowed to list the bucket contents.

    - Users granted WRITE access are allowed READ acccess and also are
      allowed to write and delete objects in that bucket -- including
      overwriting previously written objects.

    - Users granted FULL_CONTROL access are allowed WRITE access and also
      are allowed to read and write the bucket's ACL.

  The object ACL works as follows:

    - Users granted READ access are allowed to read the object's data and
      metadata.

    - Users granted FULL_CONTROL access are allowed READ access and also
      are allowed to read and write the object's ACL.

  A couple of points are worth noting, that sometimes surprise users:

  1. There is no WRITE access for objects; attempting to set an ACL with WRITE
     permission for an object will result in an error.

  2. The bucket ACL plays no role in determining who can read objects; only the
     object ACL matters for that purpose. This is different from how things
     work in Linux file systems, where both the file and directory permission
     control file read access. It also means, for example, that someone with
     FULL_CONTROL over the bucket may not have read access to objects in
     the bucket.  This is by design, and supports useful cases. For example,
     you might want to set up bucket ownership so that a small group of
     administrators have FULL_CONTROL on the bucket (with the ability to
     delete data to control storage costs), but not grant those users read
     access to the object data (which might be sensitive data that should
     only be accessed by a different specific group of users).


<B>CANNED ACLS</B>
  The simplest way to set an ACL on a bucket or object is using a "canned
  ACL". The available canned ACLs are:

  project-private            Gives permission to the project team based on their
                             roles. Anyone who is part of the team has READ
                             permission, and project owners and project editors
                             have FULL_CONTROL permission. This is the default
                             ACL for newly created buckets. This is also the
                             default ACL for newly created objects unless the
                             default object ACL for that bucket has been
                             changed. For more details see
                             "gsutil help projects".

  private                    Gives the requester (and only the requester)
                             FULL_CONTROL permission for a bucket or object.

  public-read                Gives the requester FULL_CONTROL permission and
                             gives all users READ permission. When you apply
                             this to an object, anyone on the Internet can
                             read the object without authenticating.

  public-read-write          Gives the requester FULL_CONTROL permission and
                             gives all users READ and WRITE permission. This
                             ACL applies only to buckets.

  authenticated-read         Gives the requester FULL_CONTROL permission and
                             gives all authenticated Google account holders
                             READ permission.

  bucket-owner-read          Gives the requester FULL_CONTROL permission and
                             gives the bucket owner READ permission. This is
                             used only with objects.

  bucket-owner-full-control  Gives the requester FULL_CONTROL permission and
                             gives the bucket owner FULL_CONTROL
                             permission. This is used only with objects.


<B>ACL XML</B>
  When you use a canned ACL, it is translated into an XML representation
  that can later be retrieved and edited to specify more fine grained
  detail about who can read and write buckets and objects. By running
  the gsutil getacl command you can retrieve the ACL XML, and edit it to
  customize the permissions.

  As an example, if you create an object in a bucket that has no default
  object ACL set and then retrieve the ACL on the object, it will look
  something like this:

  <AccessControlList>
    <Owner>
      <ID>
          00b4903a97163d99003117abe64d292561d2b4074fc90ce5c0e35ac45f66ad70
      </ID>
    </Owner>
    <Entries>
      <Entry>
        <Scope type="UserById">
          <ID>
              00b4903a97163d99003117abe64d292561d2b4074fc90ce5c0e35ac45f66ad70
          </ID>
        </Scope>
        <Permission>
          FULL_CONTROL
        </Permission>
      </Entry>
    </Entries>
  </AccessControlList>

  The IDs shown here are "canonical IDs", which uniquely identify individuals
  and groups.

  The ACL consists of an Owner element and a collection of Entry elements, each
  of which specifies a Scope and a Permission. Scopes are the way you specify
  an individual or group of individuals, and Permissions specify what access
  they're permitted.

  This particular ACL grants a single user (the person who uploaded the
  object in this case) FULL_CONTROL over the object, which just means
  that person is allowed to read the object and read and write the ACL.

  Here's an example of a more interesting ACL:

  <AccessControlList>
    <Entries>
      <Entry>
        <Permission>
          FULL_CONTROL
        </Permission>
        <Scope type="GroupByEmail">
          <EmailAddress>travel-companion-owners@googlegroups.com</EmailAddress>
        </Scope>
      </Entry>
      <Entry>
        <Permission>
          READ
        </Permission>
        <Scope type="GroupByEmail">
          <EmailAddress>travel-companion-readers@googlegroups.com</EmailAddress>
        </Scope>
      </Entry>
    </Entries>
  </AccessControlList>

  This ACL grants one group FULL_CONTROL, and grants a different
  (probably much larger) group READ access. By applying group grants to
  a collection of objects you can edit access control for large numbers
  of objects at once via http://groups.google.com. That way, for example,
  you can easily and quickly change access to a group of company objects
  when employees join and leave your company (i.e., without having to
  individually change ACLs across potentially millions of objects).


<B>CANONICAL IDS VS. HUMAN READABLE IDENTIFIERS</B>
  The first ACL in the previous section contained canonical IDs, while the
  second contained email address-based identifiers. The reason for canonical IDs
  is to guard user privacy, so that by default the names and email addresses
  of sharees aren't visible (even to those users who are allowed to view
  and edit the ACL). If hiding user identities is not needed for your case
  and you'd like to have the ACLs contain human-readable addresses you can
  add a DisplayName element to each Scope you put in the ACL. For example,
  the second ACL above could be edited to contain this information:

  <AccessControlList>
    <Entries>
      <Entry>
        <Permission>
          FULL_CONTROL
        </Permission>
        <Scope type="GroupByEmail">
          <EmailAddress>travel-companion-owners@googlegroups.com</EmailAddress>
          <DisplayName>travel-companion-owners@googlegroups.com</DisplayName>
        </Scope>
      </Entry>
      <Entry>
        <Permission>
          READ
        </Permission>
        <Scope type="GroupByEmail">
          <EmailAddress>travel-companion-readers@googlegroups.com</EmailAddress>
          <DisplayName>travel-companion-readers@googlegroups.com</DisplayName>
        </Scope>
      </Entry>
    </Entries>
  </AccessControlList>

  When written this way, even though the original identity will be translated
  by the Google Cloud Storage service into a canonical ID when retrieved later,
  the DisplayName field will be left with whatever content you wrote (the
  email address in the above case).


<B>PROJECT GROUPS</B>
  Google Cloud Storage buckets are owned by projects. Associated with each
  project is an owners group, an editors group, and a viewers group. In short,
  these groups make it easy to set up a bucket and start uploading objects
  with access control appropriate for a project at your company, as the three
  group memberships can be configured by your administrative staff. Control
  over projects and their associated memberships is provided by the Google
  APIs Console (https://code.google.com/apis/console).


<B>SHARING SCENARIOS</B>
  For more detailed examples how to achieve various useful sharing use
  cases see https://developers.google.com/storage/docs/collaboration
""")


class CommandOptions(HelpProvider):
  """Additional help about Access Control Lists."""

  help_spec = {
    # Name of command or auxiliary help info for which this help applies.
    HELP_NAME : 'acls',
    # List of help name aliases.
    HELP_NAME_ALIASES : ['acl', 'ACL', 'access control', 'access control list',
                         'authorization', 'canned', 'canned acl'],
    # Type of help:
    HELP_TYPE : HelpType.ADDITIONAL_HELP,
    # One line summary of this help.
    HELP_ONE_LINE_SUMMARY : 'Working with Access Control Lists',
    # The full help text.
    HELP_TEXT : _detailed_help_text,
  }
