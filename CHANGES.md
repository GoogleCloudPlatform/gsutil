Release 4.0 beta 1 (release date: 2014-01-31)
=======================================

New Features
------------
- The Google Cloud Storage JSON API (v1beta2) is now the default API used
  by gsutil for all commands targeting gs:// URLs. The JSON API is more
  bandwidth efficient than the older XML API when transferring metadata
  and does not require separate calls to preserve object ACLs when copying.
- The Google Cloud Storage XML API can be used in lieu of the JSON API
  by setting 'force_api = xml' in the GSUtil section of your boto config file.

Backwards-incompatible changes
------------------------------
- The Google Cloud Storage configuration data supported by the acl, cors,
  and lifecycle commands uses the JSON format instead of the older XML format.
  gsutil 4.0 will fail and provide conversion instructions if an XML
  configuration file is provided as an argument for a gs:// URL.
- gsutil no longer accepts arbitrary headers via the global -h flag.
  Documented headers for gsutil commands are still supported; for the
  full list of supported headers, see `gsutil help command_opts`.
- The compose command will now default the destination object's
  Content-Type to the Content-Type of the first source object if none
  is provided via the -h global flag.
- The long-deprecated -t option has been removed from the cp command.

Other Changes
-------------
- All python files not under a third_party directory are now pylint-clean,
  with the exception of TODO-format and a handful of warnings in root-level
  files. As part of the de-linting process, many edge-case bugs were
  identified and fixed.
- The ls command now operates depth-first (as in Unix ls) instead
  of breadth-first.
- 'URI' has now been replaced throughout much of the codebase with the
  more appropriate term 'URL'.
- The wildcard and name expansion iterators have been heavily refactored.
- A new abstraction layer ('gsutil Cloud API') has been implemented to allow
  gsutil to interact with JSON and XML APIs interchangeably.
- A new URL abstraction layer ('StorageUrl') has been implemented to
  interact with URL strings without making HTTP calls.
- Resumable upload and download handling and tracker files are now managed
  by the cp command instead of using the handlers in the boto library.

Beta Disclaimers
----------------
- There are some gsutil 3.x features that are not yet supported in the
  4.0 beta. These are denoted in the code by 'TODO: gsutil-beta' and
  will be implemented before the final 4.0 release. Notable omissions
  include:
  - Parallel composite upload support.
  - Perfdiag host header support.
  - On-the-fly hash computation for resumable uploads.
  - In-memory daisy-chain copying support (for now, a temporary file is used).
  - Progress indicator for streaming uploads.
  - Efficient credential refresh for long-running multi-process operations.
  - Bucket relocate scripts (they will fail at present).


Release 3.42 (release-date: 2014-01-15)
=======================================

Other Changes
-------------

- Fixed potential bug with update command on CentOS.


Release 3.41 (release-date: 2014-01-14)
=======================================

Other Changes
-------------

- Changes to protect security of resumable upload IDs.


Release 3.40: Skipped


Release 3.39: Skipped


Release 3.38 (release-date: 2013-11-25)

Bug Fixes
---------

- Fix to include version number in user-agent string.
- Fix bug wherein -m flag or parallel uploads caused crash on systems without
  /dev/shm.
- Fix SSL errors and invalid results with perfdiag -c and -k rthru test.
- Fixed cases where parallel composite uploads could leave orphaned components.
- Fix bug attempting to stat objects you don't have auth to read.
- Fixed bug breaking defacl's -d option.


Other Changes
-------------

- Fixed gsutil config doc.
- Fixed references to old command names; fix defacl ch example.
- Improved error messages for deprecated command aliases.
- Updated gsutil support info.


New Features
------------

- Enabled -R flag for recursion with setmeta command.


Release 3.37 (release-date: 2013-09-25)
=======================================

Bug Fixes
---------

- Fix parsing of -R for "acl ch" and chacl commands.
- Fixed import statement of unittest2 which caused installations using Python
  2.6 without unittest2 installed to fail when starting up gsutil.


Other Changes
-------------

- Fixed tests so they pass on Windows and package installs.
- Add a root logging handler manually instead of relying on basicConfig.
- Fix apiclient import statement.
- Exponential backoff for access token requests.
- Fix flakiness in test TearDown to account for eventual consistency of object
  listings.


Release 3.36 (release-date: 2013-09-18)
=======================================

Bug Fixes
---------

- Fix bug when a 400 or 403 exception has no detail.
- Fix bugs with config -e and config -o.


Other Changes
-------------

- Clarify stat command documentation regarding trailing slashes.
- Add Generation and Metageneration to gsutil stat output.


New Features
------------

- Set config values from command line with -o.


Release 3.35 (release-date: 2013-09-09)
=======================================

Bug Fixes
---------

- Fix streaming upload to S3 and provide more useful stack traces multi-threaded failures.
- Fix race condition in test_rm.
- Fix retry decorator during test bucket cleanup.
- Fixed cat bug that caused version to be ignored in URIs.
- Don't decode -p or -h values other than x-goog-meta-. Fixes ability to use string project names.
- Update bucket_relocate.sh to work on GCE.
- Fix recursive uploading from subdirectories with unexpanded wildcard as source URI.
- Make gsutil error text include <Message> content.
- Change shebang line back to python because this doesn't work on some systems.
- Fix hash_algs differences in perfdiag.
- Update Python version check and shebang line.
- Enforce project_id entry in config command; provide friendly error if missing proj ID.
- Use transcoding-invariant headers when available in gs.Key.
- Make gsutil cp not fail if unable to check versioning config on dest bucket.
- Make gsutil detect when config fails because of proxy and prompt for proxy config.
- Avoid checking metageneration attribute when long-listing S3 objects.
- Exclude the no-op auth handler as indicating credentials are configured.


New Features
------------

- Implemented gsutil stat command.


Other Changes
-------------

- Consolidate config-related commands.
- Changed rm -r gs://bucket to delete bucket at end.
- Various doc cleanup and improvement.
- Warn user before updating to major new version. Also fixed minor version comparison bug, and added tests.
- Change max component count to 1024.
- Add retry-decorator as a submodule.
- Explicitly state control chars to avoid in gsutil naming documentation.
- Make config command recommend project strings.
- Made long listing format a little better looking.
- Allow --help flag for subcommands.
- Implement help for subcommands and add OPTIONS sections for subcommands.
- Add more detailed error message to notification watchbucket command.
- Add notification URL configuration for notification tests.
- Refactor to use upstream retry_decorator as external dependency.
- Distribute cacerts file with gsutil.
- Updated gsutil help to point to Google Cloud Console instead of older APIs console.
- Make gsutil pass bundled cacerts.txt to oauth2client; stop checking SHA1 of certs, now that we no longer depend on boto distribution.
- Move all TTY checks to a common util function and mock it for update tests.
- Fix duplicate entry created in .gitmodules.
- Fix unit test breakage because VERSION file is old.
- Fix test using ? glob with ObjectToURI.
- Fix update tests that fail for package installs.
- Change bucket delete teardown to try more times.
- Fix tests that perform operations on bucket listings.
- Keep package install set to True unless VERSION file doesn't exist.
- Fix handling of non-numeric version strings in update test.


Release 3.34 (release-date: 2013-07-18)
=======================================

Bug Fixes
---------

- Fixed a bug where the no-op authentication handler was being loaded after
  other authentication plugins, causing the no-op handler to be chosen instead
  of other valid credentials.


Release 3.33 (release-date: 2013-07-16)
=======================================

Bug Fixes
---------

- Added .git* to MANIFEST.in excludes and fixed cp doc typo. This was needed to
  overcome problem caused by accidental inclusion of .git* files in release,
  which caused the update command no longer to allow updates (since starting
  in 3.32 it checks whether the user has any extraneous files in the gsutil
  directory before updating)


Release 3.32 (release-date: 2013-07-16)
=======================================

New Features
------------

- Added support for getting and setting lifecycle configuration for buckets.
- Implemented Parallel Composite Uploads.
- Added a new du command that displays object size, similar to Linux du.


Bug Fixes
---------

- Fixed a bug when using ls -R on objects with trailing slashes. Closes #93.
- Fixed so won't crash in perfdiag when nslookup is missing or gethostbyname
  fails.
- Smartly compare version strings during autoupdate check.
- Made header handling for upload case-insensitive.
- Re-enabled software update check for users with no credentials configured.
- Fixed incorrectly-generated password editing comment in service account
  config. Fixes #146.


Other Changes
-------------

- Improved flow when encounter auth failure for GCE service account with no
  configured storage scopes:
    1. Changed HasConfiguredCredentials() logic not to include
       has_auth_plugins as part of the evaluated expression, since that will
       always evaluate to true under GCE (since GCE configures its internal
       service account plugin under /etc/boto.cfg).
    2. Changed ConfigureNoOpAuthIfNeeded logic so we configure no-op auth
       plugin even if there is a config_file list, since GCE always configures
       /etc/boto.cfg, even if user has no storage scopes configured.
    3. Additional changes:
      a. Removed assertion of oauth access token cache check log from
         test_Doption.py, which may not be true sometimes (e.g., if user is
         using HMAC creds).
      b. Removed remnants of CONFIG_REQUIRED left over from earlier CL.
      c. Merged dupe _ConfigureNoOpAuthIfNeeded functions from two code files,
         moved to util.py.
- Fixed confusing gsutil rm "Omitting" message.
- Wrapped long gsutil update message.
- Silenced additional possible perfdiag errors.
- Improved perfdiag performance by only generating one chunk of random file.
- Changed to swallow broken pipe errors when piping gsutil to other programs.
- Made DotfulBucketNameNotUnderTld error message more user friendly.
- Extracted function for building ACL error text from main try/except loop,
  for better readability.
- Disallowed gsutil update when user data present in gsutil dir.
- Plumbed accept-encoding into HEAD requests in ls -L command.
- Updated README and moved ReleaseNotes.txt to CHANGES.md.
- Updated crcmod docs with link to Windows installer.
- Updated documentation regarding gzip content-encoding.
- Removed StorageUri parse check for lone ':' (interferes with using filenames
  containing ':')
- Added tests for gsutil update check and fixed bug for bad file contents.
- Set accept-encoding and handle gzip on-the-fly encoding.


Release 3.31 (release-date: 2013-06-10)
=======================================

New Features
------------

- Implemented consumption of manifest files for cp.
- Add ETag to ls -l and make ls -b variants more efficient.
- Expand the manifest path to allow for tildes in paths.
- Added bucket_relocate.sh script to gsutil.


Bug Fixes
---------

- Fix gsutil cp -R to copy all versioned objects.
- Fixed bug where gsutil cp -D -n caused precondition failure.
- Fixed gsutil daisy-chain copy to allow preserving ACLs when copying within
  same provider.
- Fix identification of non-MD5 ETags.
- Fixed bugs where gsutil -q cp and gsutil cp -q sometimes weren't quiet.
- Fixed unicode error when constructing tracker filename from non-ASCII
  Unicode filename.
- Fixed that noclobber would not resume partial resumable downloads.
- Fixed bug when running gsutil cp -Dp by user other than object owner.
- Properly encode metageneration and etag in ls output with -a and -e.
- Update resumable threshold stated in gsutil help prod.


Other Changes
-------------

- ls -Lb no longer shows total # files/total size of bucket, so that ls -Lb
  instead provides an efficient way to view just the metadata for large buckets.
- Catch and ignore EEXIST error when creating gsutil tracker dir.
- Add note to gsutil update doc about auto-update checks being disabled with
  gsutil -q option.
- Disable hashing and increase buffer size in perfdiag.
- Added better error messages for service account auth.
- Make perfdiag behave more like normal gsutil, with multi-threading option.
- Changed so auto-update check/prompt aren't made if gsutil -q specified.
- Changed gsutil mb command to clarify that EU means European Union.
- Added doc warnings about losing version ordering if using gsutil -m cp
  between versioned buckets; removed trailing whitespace.
- Added to gsutil cp -L doc to describe how to build a reliable script for
  copying many objects.


Release 3.30 (release-date: 2013-06-10)
=======================================

- Abandoned.


Release 3.29 (release-date: 2013-05-13)
=======================================

Bug Fixes
---------

- Fixed incorrect package installation detection that resulted in not being
  able to run the update command while running gsutil from a symlink.

Other Changes
-------------

- Added a test for debug mode (gsutil -D) output.
- List numbering and title case fixes in additional help pages.
- Removed dateutil module dependency from cp command test.
- Updated documentation to clarify that public-read objects are cached for 1
  hour by default.
- Added a filter to suppress "module was already imported" warnings that were
  sometimes printed while running gsutil on Google Compute Engine instances.


Release 3.28 (release-date: 2013-05-07)
=======================================

New Features
------------

- Added support for new Object Change Notifications feature.

Bug Fixes
---------

- Fixed problem where gsutil update command didn’t take default action.
- Fixed a problem with the update command sometimes triggering an additional
  update command.

Other Changes
-------------

- Add packaging information to version output.
- Removed fancy_urllib, since it is no longer used.
- Changed num_retries default for resumable downloads to 6.
- Don’t check for newer software version if gs_host is specified in boto
  config file.
- Modified oauth2client logging behavior to be consistent with gsutil.
- Added gs_port configuration option.
- Skip update tests when SSL is disabled.


Release 3.27 (release-date: 2013-04-25)
=======================================

New Features
------------

- Added a human readable option (-h) to ls command.
- Changed WildcardIterator not to materialize list of all matching files from
  directory listing (so works faster when walking over large directories)
- Added -f option to setacl command to allow command to continue after errors
  encountered.
- Add manifest log support for the cp command.
- Added never option for check_hashes_config; fixed bug that assumes an ETag
  is always returned from server.
- Made gsutil provide friendlier error message if attempting non-public data
  access with missing credentials.
- Set 70 second default socket timeout for httplib.
- Add ability to run a single test class or function with the test command.

Bug Fixes
---------

- Don't check for updates if the user has no credentials configured. This
  fixes a bug for users without credentials trying to use gsutil for first
  time.
- Fixed case where chacl command incorrectly recognized an email address as a
  domain.
- Fix setmeta command for S3 objects.
- Fixed bug where wildcarded dest URI attempted string op on Key object.
- Fixed case where gsutil -q outputted progress output when doing a streaming
  upload.
- Error handling for out of space during downloads.
- Include ISO 8601-required "Z" at end of timestamp string for gsutil ls -l,
  to be spec-compliant.
- Removed deprecated setmeta syntax and fixed unicode issues.
- Changed update command not to suggest running sudo if running under Cygwin.
- Removed references to deprecated gs-discussion forum from gsutil built-in
  help.
- Add literal quotes around CORS config example URL in gsutil setcors help to
  avoid having example URL turn into an HREF in auto-generated doc.

Other Changes
-------------

- Added proper setup.py to make gsutil installable via PyPi.
- Added warning to gsutil built-in help that delete operations cannot be
  undone.
- Replaced gsutil's OAuth2 client implementation with oauth2client.
- Updates to perfdiag.
- Updated config help about currently supported settings.
- Fixes to setup.py and modified version command.
- Move gslib/commands/cred_types.py to gslib, so only Command subclasses live
  in gslib/commands.
- Updated gsutil setmeta help no longer to warn that setmeta with versioning
  enabled creates a new object.


Release 3.26 (release-date: 2013-03-25)
=======================================

New Features
------------

- Added support for object composition.
- Added support for external service accounts.
- Changed gsutil to check for available updates periodically (only while
  stdin, stderr, stdout are connected to a TTY, so as not to interfere with
  cron jobs).
- Added chdefacl command.
- Made gsutil built-in help available under
  https://developers.google.com/storage/docs/gsutil
- Add a command suggestion when the command name is not found.
- Added byte suffix parsing to the -s parameter of perfdiag.
- Added --help support to subcommands. Fixes #96.
- Updated perfdiag command to track availability and record TCP settings.
- Added metadata parameter to perfdiag command.
- Added support for specifying byte range to cat command.
- Output more bucket metadata on ls -Lb.
- Implemented gsutil -q (global quiet) option (fixes issue #130). Also changed
  gsutil to output all progress indicators using logging levels. Also changed
  help command not to output bold escape sequences and not use PAGER if stdout
  is not a tty, which also fixes bug that caused gsutil help test to fail.
- Plumbed https_validate_certificates through to OAuth2 plugin handler,
  allowing control over cert validation for OAuth2 requests
- Fixed ISO 639.1 ref in config command help text

Bug Fixes
---------

- Fixed bug where gsutil cp -D didn't preserve metadata
- Fixed problem where gsutil -m is hard to interrupt (partial fix for issue
  #99 - only for Linux/MacOS; problem still exists for Windows).
- Fixed broken reference to boto_lib_dir in update command.
- Made changing ACL not retry on 400 error.
- Fixed name expansion bug for case where uri_strs is itself an iterator
  (issue #131); implemented additional naming unit test for this case.
- Fixed flaky gsutil rm test
- Fixed a bug in the chacl command that made it so you couldn't delete the
  AllAuthenticatedUsers group from an ACL.

Other Changes
-------------

- Refactored gsutil main function into gslib, with gsutil being a thin
  wrapper.
- Added a test for the update command.
- Renamed gsutil meta_generation params to metageneration, for consistency
  with GCS docs.
- Removed .pyc files from tarball/zipfile.
- Added new root certs to cacerts.txt, to provide additional flexibility
  in the future.


Release 3.25 (release-date: 2013-02-21)
=======================================

Bug Fixes
---------

- Fixed two version-specific URI bugs:
    1. gsutil cp -r gs://bucket1 gs://bucket2 would create objects in bucket2
       with names corresponding to version-specific URIs in bucket1 (e.g.,
       gs://bucket2/obj#1361417568482000, where the "#1361417568482000" part was
       part of the object name, not the object's generation).

       This problem similarly caused gsutil cp -r gs://bucket1 ./dir to create
       files names corresponding to version-specific URIs in bucket1.
    2. gsutil rm -a gs://bucket/obj would attempt to delete the same object
       twice, getting a NoSuchKey error on the second attempt.


Release 3.24 (release-date: 2013-02-19)
=======================================

Bug Fixes
---------

- Fixed bug that caused attempt to dupe-encode a unicode filename.

Other Changes
-------------

- Refactored retry logic from setmeta and chacl to use @Retry decorator.
- Moved @Retry decorator to third_party.
- Fixed flaky tests.


Release 3.23 (release-date: 2013-02-16)
=======================================

Bug Fixes
---------

- Make version-specific URI parsing more robust. This fixes a bug where
  listing buckets in certain cases would result in the error
  'BucketStorageUri' object has no attribute 'version_specific_uri'


Release 3.22 (release-date: 2013-02-15)
=======================================

New Features
------------

- Implemented new chacl command, which makes it easy to add and remove bucket
  and object ACL grants without having to edit XML (like the older setacl
  command).
- Implemented new "daisy-chain" copying mode, which allows cross-provider
  copies to run without buffering to local disk, and to use resumable uploads.
  This copying mode also allows copying between locations and between storage
  classes, using the new gsutil cp -D option. (Daisy-chain copying is the
  default when copying between providers, but must be explicitly requested for
  the other cases to keep costs and performance expectations clear.)
- Implemented new perfdiag command to run a diagnostic test against
  a bucket, collect system information, and report results. Useful
  when working with Google Cloud Storage team to resolve questions
  about performance.
- Added SIGQUIT (^\) handler, to allow breakpointing a running gsutil.

Bug Fixes
---------

- Fixed bug where gsutil setwebcfg signature didn't match with
  HMAC authentication.
- Fixed ASCII codec decode error when constructing tracker filename
  from non-7bit ASCII input filename.
- Changed boto auth plugin framework to allow multiple plugins
  supporting requested capability, which fixes gsutil exception
  that used to happen where a GCE user had a service account
  configured and then ran gsutil config.
- Changed Command.Apply method to be resilient to name expansion
  exceptions. Before this change, if an exception was raised
  during iteration of NameExpansionResult, the parent process
  would immediately stop execution, causing the
  _EOF_NAME_EXPANSION_RESULT to never be sent to child processes.
  This resulted in the process hanging forever.
- Fixed various bugs for gsutil running on Windows:
  - Fixed various places from a hard-coded '/' to os.sep.
  - Fixed a bug in the cp command where it was using the destination
    URI's .delim property instead of the source URI.
  - Fixed a bug in the cp command's _SrcDstSame function by
    simplifying it to use os.path.normpath.
  - Fixed windows bug in tests/util.py _NormalizeURI function.
  - Fixed ZeroDivisionError sometimes happening during unit tests
    on Windows.

- Fixed gsutil rm bug that caused exit status 1 when encountered
  non-existent URI.
- Fixed support for gsutil cp file -.
- Added preconditions and retry logic to setmeta command, to
  enforce concurrency control.
- Fixed bug in copying subdirs to subdirs.
- Fixed cases where boto debug_level caused too much or too little
  logging:
  - resumable and one-shot uploads weren't showing response headers
    when connection.debug > 0.
  - payload was showing up in debug output when connection.debug
    < 4 for streaming uploads.

- Removed XML parsing from setacl. The previous implementation
  relied on loose XML handling, which could truncate what it sends
  to the service, allowing invalid XML to be specified by the
  user. Instead now the ACL XML is passed verbatim and we rely
  on server-side schema enforcement.
- Added user-agent header to resumable uploads.
- Fixed reporting bits/s when it was really bytes/s.
- Changed so we now pass headers with API version & project ID
  to create_bucket().
- Made "gsutil rm -r gs://bucket/folder" remove xyz_$folder$ object
  (which is created by various GUI tools).
- Fixed bug where gsutil binary was shipped with protection 750
  instead of 755.

Other Changes
-------------

- Reworked versioned object handling:
  - Removed need for commands to specify -v option to parse
    versions. Versioned URIs are now uniformly handled by all
    commands.
  - Refactored StorageUri parsing that had been split across
    storage_uri and convenience; made versioned URIs render with
    version string so StorageUri is round-trippable (boto change).
  - Implemented gsutil cp -v option for printing the version-specific
    URI that was just created.
  - Added error detail for attempt to delete non-empty versioned
    bucket. Also added versioning state to ls -L -b gs://bucket
    output.
  - Changed URI parsing to use pre-compiled regex's.
  - Other bug fixes.

- Rewrote/deepened/improved various parts of built-in help:
  - Updated 'gsutil help dev'.
  - Fixed help command handling when terminal does not have the
    number of rows set.
  - Rewrote versioning help.
  - Added gsutil help text for common 403 AccountProblem error.
  - Added text to 'gsutil help dev' about legal agreement needed
    with code submissions.
  - Fixed various other typos.
  - Updated doc for cp command regarding metadata not being
    preserved when copying between providers.
  - Fixed gsutil ls command documentation typo for the -L option.
  - Added HTTP scheme to doc/examples for gsutil setcors command.
  - Changed minimum version in documentation from 2.5 to 2.6 since
    gsutil no longer works in Python 2.5.
  - Cleaned up/clarify/deepen various other parts of gsutil
    built-in documentation.

- Numerous improvements to testing infrastructure:
  - Completely refactored infrastructure, allowing deeper testing
    and more readable test code, and enabling better debugging
    output when tests fail.
  - Moved gslib/test_*.py unit tests to gslib/tests module.
  - Made all tests (unit and integration, per-command and modules
    (like naming) run from single gsutil test command.
  - Moved TempDir functions from GsUtilIntegrationTestCase to
    GsUtilTestCase.
  - Made test runner message show the test function being run.
  - Added file path support to ObjectToURI function.
  - Disabled the test command if running on Python 2.6 and unittest2
    is not available instead of breaking all of gsutil.
  - Changed to pass GCS V2 API and project_id from boto config
    if necessary in integration_testcase#CreateBucket().
  - Fixed unit tests by using a GS-specific mocking class to
    override the S3 provider.
  - Added friendlier error message if test path munging fails.
  - Fixed bug where gsutil test only cleaned up first few test files.
  - Implemented setacl integration tests.
  - Implemented StorageUri parsing unit tests.
  - Implemented test for gsutil cp -D.
  - Implemented setacl integration tests.
  - Implemented tests for reading and seeking past end of file.
  - Implemented and tests for it in new tests module.
  - Changed cp tests that don't specify a Content-Type to check
    for new binary/octet-stream default instead of server-detected
    mime type.

- Changed gsutil mv to allow moving local files/dirs to the cloud.
  Previously this was disallowed in the belief we should be
  conservative about deleting data from local disk but there are
  legitimate use cases for moving data from a local dir to the
  cloud, it's clear to the user this would remove data from the
  local disk, and allowing it makes the tool behavior more
  consistent with what users would expect.
- Changed gsutil update command to insist on is_secure and
  https_validate_certificates.
- Fixed release no longer to include extraneous boto dirs in
  top-level of gsutil distribution (like bin/ and docs/).
- Changed resumable upload threshold from 1 MB to 2 MB.
- Removed leftover cloudauth and cloudreader dirs. Sample code
  now lives at https://github.com/GoogleCloudPlatform.
- Updated copyright notice on code files.


Release 3.21 (release-date: 2012-12-10)
=======================================

New Features
------------

- Added the ability for the cp command to continue even if there is an
  error. This can be activated with the -c flag.
- Added support for specifying src args for gsutil cp on stdin (-I option)

Bug Fixes
---------

- Fixed gsutil test cp, which assumed it was run from gsutil install dir.
- Mods so we send generation subresource only when user requested
  version parsing (-v option for cp and cat commands).

Other Changes
-------------

- Updated docs about using setmeta with versioning enabled.
- Changed GCS endpoint in boto to storage.googleapis.com.


Release 3.20 (release-date: 2012-11-30)
=======================================

New Features
------------

- Added a noclobber (-n) setting for the cp command. Existing objects/files
  will not be overwritten when using this setting.

Bug Fixes
---------

- Fixed off-by-one error when reporting bytes transferred.

Other Changes
-------------

- Improved versioning support for the remove command.
- Improved test runner support.


Release 3.19 (release-date: 2012-11-26)
=======================================

New Features
------------

- Added support for object versions.
- Added support for storage classes (including Durable Reduced Availability).

Bug Fixes
---------
- Fixed problem where cp -q prevented resumable uploads from being performed.
- Made setwebcfg and setcors tests robust wrt XML formatting variation.

Other Changes
-------------

- Incorporated vapier@ mods to make version command not fail if CHECKSUM file
  missing.
- Refactored gsutil such that most functionality exists in boto.
- Updated gsutil help dev instructions for how to check out source.


Release 3.18 (release-date: 2012-09-19)
=======================================

Bug Fixes
---------

- Fixed resumable upload boundary condition when handling POST request
  when server already has complete file, which resulted in an infinite
  loop that consumed 100% of the CPU.
- Fixed one more place that outputted progress info when gsutil cp -q
  specified (during streaming uploads).

Other Changes
-------------

- Updated help text for "gsutil help setmeta" and "gsutil help metadata", to
  clarify and deepen parts of the documentation.


Release 3.17 (release-date: 2012-08-17)
=======================================

Bug Fixes
---------

- Fixed race condition when multiple threads attempt to get an OAuth2 refresh
  token concurrently.

Other Changes
-------------

- Implemented simplified syntax for setmeta command. The old syntax still
  works but is now deprecated.
- Added help to gsutil cp -z option, to describe how to change where temp
  files are written.


Release 3.16 (release-date: 2012-08-13)
=======================================

Bug Fixes
---------

- Added info to built-in help for setmeta command, to explain the syntax
  needed when running from Windows.


Release 3.15 (release-date: 2012-08-12)
=======================================

New Features
------------

- Implemented gsutil setmeta command.
- Made gsutil understand bucket subdir conventions used by various tools
  (like GCS Manager and CloudBerry) so if you cp or mv to a subdir you
  created with one of those tools it will work as expected.
- Added support for Windows drive letter-prefaced paths when using Storage
  URIs.

Bug Fixes
---------

- Fixed performance bug when downloading a large object with Content-
  Encoding:gzip, where decompression attempted to load the entire object
  in memory. Also added "Uncompressing" log output if file is larger than
  50M, to make it clear the download hasn't stalled.
- Fixed naming bug when performing gsutil mv from a bucket subdir to
  and existing bucket subdir.
- Fixed bug that caused cross-provider copies into Google Cloud Storage to
  fail.
- Made change needed to make resumable transfer progress messages not print
  when running gsutil cp -q.
- Fixed copy/paste error in config file documentation for
  https_validate_certificates option.
- Various typo fixes.

Other Changes
-------------

- Changed gsutil to unset http_proxy environment variable if it's set,
  because it confuses boto. (Proxies should instead be configured via the
  boto config file.)


Release 3.14 (release-date: 2012-07-28)
=======================================

New Features
------------

- Added cp -q option, to support quiet operation from cron jobs.
- Made config command restore backed up file if there was a failure or user
  hits ^C.

Bug Fixes
---------

- Fixed bug where gsutil cp -R from a source directory didn't generate
  correct destination path.
- Fixed file handle leak in gsutil cp -z
- Fixed bug that caused cp -a option not to work when copying in the cloud.
- Fixed bug that caused '/-' to be appended to object name for streaming
  uploads.
- Revert incorrect line I changed in previous CL, that attempted to
  get fp from src_key object. The real fix that's needed is described in
  https://github.com/GoogleCloudPlatform/gsutil/issues/72.

Other Changes
-------------

- Changed logging to print "Copying..." and Content-Type on same line;
  refactored content type and log handling.


Release 3.13 (release-date: 2012-07-19)
=======================================

Bug Fixes
---------

- Included the fix to make 'gsutil config' honor BOTO_CONFIG environment
  variable (which was intended to be included in Release 3.12)


Release 3.11 (release-date: 2012-06-28)
=======================================

New Features
------------

- Added support for configuring website buckets.

Bug Fixes
---------

- Fixed bug that caused simultaneous resumable downloads of the same source
  object to use the same tracker file.
- Changed language code spec pointer from Wikipedia to loc.gov (for
  Content-Language header).


Release 3.10 (release-date: 2012-06-19)
=======================================

New Features
------------

- Added support for setting and listing Content-Language header.

Bug Fixes
---------

- Fixed bug that caused getacl/setacl commands to get a character encoding
  exception when ACL content contained content not representable in ISO-8859-1
  character set.
- Fixed gsutil update not to fail under Windows exclusive file locking.
- Fixed gsutil ls -L to continue past 403 errors.
- Updated gsutil tests and also help dev with instructions on how to run
  boto tests, based on recent test refactoring done to in boto library.
- Cleaned up parts of cp help text.


Release 3.9 (release-date: 2012-05-24)
======================================

Bug Fixes
---------

- Fixed bug that caused extra "file:/" to be included in pathnames with
  doing gsutil cp -R on Windows.


Release 3.8 (release-date: 2012-05-20)
======================================

Bug Fixes
---------

- Fixed problem with non-ASCII filename characters not setting encoding before
  attempting to hash for generating resumable transfer filename.


Release 3.7 (release-date: 2012-05-11)
======================================

Bug Fixes
---------

- Fixed handling of HTTPS tunneling through a proxy.


Release 3.6 (release-date: 2012-05-09)
======================================

Bug Fixes
---------

- Fixed bug that caused wildcards spanning directories not to work.
- Fixed bug that gsutil cp -z not to find available tmp space correctly
  under Windows.


Release 3.5 (release-date: 2012-04-30)
======================================

Performance Improvement
-----------------------

- Change by Evan Worley to calculate MD5s incrementally during uploads and
  downloads. This reduces overall transfer time substantially for large
  objects.

Bug Fixes
---------

- Fixed bug where uploading and moving multiple files to a bucket subdirectory
  didn't work as intended.
  (https://github.com/GoogleCloudPlatform/gsutil/issues/92).
- Fixed bug where gsutil cp -r sourcedir didn't copy to specified subdir
  if there is only one file in sourcedir.
- Fixed bug where tracker file included a timestamp that caused it not to
  be recognized across sessions.
- Fixed bug where gs://bucket/*/dir wildcard matches too many objects.
- Fixed documentation errors in help associated with ACLs and projects.
- Changed GCS ACL parsing to be case-insensitive.
- Changed ls to print error and exit with non-0 status when wildcard matches
  nothing, to be more consistent with UNIX shell behavior.


Release 3.4 (release-date: 2012-04-06)
======================================

Bug Fixes
---------

- Fixed problem where resumable uploads/downloads of objects with very long
  names would generate tracking files with names that exceeded local file
  system limits, making it impossible to complete resumable transfers for
  those objects. Solution was to build the tracking file name from a fixed
  prefix, SHA1 hash of the long filename, epoch timestamp and last 16
  chars of the long filename, which is guarantee to be a predictable and
  reasonable length.
- Fixed minor bug in output from 'gsutil help dev' which advised executing
  an inconsequential test script (test_util.py).


Release 3.3 (release-date: 2012-04-03)
======================================

Bug Fixes
---------

- Fixed problem where gsutil ver and debug flags crashed when used
  with newly generated boto config files.
- Fixed gsutil bug in windows path handling, and make checksumming work
  across platforms.
- Fixed enablelogging to translate -b URI param to plain bucket name in REST
  API request.


Release 3.2 (release-date: 2012-03-30)
======================================

Bug Fixes
---------

- Fixed problem where gsutil didn't convert between OS-specific directory
  separators when copying individually-named files (issue 87).
- Fixed problem where gsutil ls -R didn't work right if there was a key
  with a leading path (like /foo/bar/baz)


Release 3.1 (release-date: 2012-03-20)
======================================

Bug Fixes
---------

- Removed erroneous setting of Content-Encoding when a gzip file is uploaded
  (vs running gsutil cp -z, when Content-Encoding should be set). This
  error caused users to get gsutil.tar.gz file uncompressed by the user
  agent (like wget) while downloading, making the file appear to be of the
  wrong size/content.
- Fixed handling of gsutil help for Windows (previous code depended on
  termios and fcntl libs, which are Linux/MacOS-specific).


Release 3.0 (release-date: 2012-03-20)
======================================

Important Notes
---------------

- Backwards-incompatible wildcard change:
  The '*' wildcard now only matches objects within a bucket directory. If
  you have scripts that depend on being able to match spanning multiple
  directories you need to use '**' instead. For example, the command:

        gsutil cp gs://bucket/*.txt

  will now only match .txt files in the top-level directory.

        gsutil cp gs://bucket/**.txt

  will match across all directories.
- gsutil ls now lists one directory at a time. If you want to list all objects
  in a bucket, you can use:

        gsutil ls gs://bucket/**

  or:

        gsutil ls -R gs://bucket

New Features
------------

- Built-in help for all commands and many additional topics. Try
  "gsutil help" for a list of available commands and topics.
- A new hierarchical file tree abstraction layer, which makes the flat bucket
  name space look like a hierarchical file tree. This makes several things
  possible:
  - copying data to/from bucket sub-directories (see “gsutil help cp”).
  - distributing large uploads/downloads across many machines
    (see “gsutil help cp”)
  - renaming bucket sub-directories (see “gsutil help mv”).
  - listing individual bucket sub-directories and for listing directories
    recursively (see “gsutil help ls”).
  - setting ACLs for objects in a sub-directory (see “gsutil help setacl”).

- Support for per-directory (*) and recursive (**) wildcards. Essentially,
  ** works the way * did in previous gsutil releases, and * now behaves
  consistently with how it works in command interpreters (like bash). The
  ability to specify directory-only wildcards also enables a number of use
  cases, such as distributing large uploads/downloads by wildcarded name. See
  "gsutil help wildcards" for details.
- Support for Cross-Origin Resource Sharing (CORS) configuration. See "gsutil
  help cors" for details.
- Support for multi-threading and recursive operation for setacl command
  (see “gsutil help setacl”).
- Ability to use the UNIX 'file' command to do content type recognition as
  an alternative to filename extensions. 
- Introduction of new end-to-end test suite.
- The gsutil version command now computes a checksum of the code, to detect
  corruption and local modification when assisting with technical support.
- The gsutil update command is no longer beta/experimental, and now also
  supports updating from named URIs (for early/test releases).
- Changed gsutil ls -L to also print Content-Disposition header.

Bug Fixes
---------

- The gsutil cp -t option previously didn't work as documented, and instead
  Content-Type was always detected based on filename extension. Content-Type
  detection is now the default, the -t option is deprecated (to be removed in
  the future), and specifying a -h Content-Type header now correctly overrides
  the filename extension based handling. For details see "gsutil help
  metadata".
- Fixed bug that caused multi-threaded mv command not to percolate failures
  during the cp phase to the rm phase, which could under some circumstances
  cause data that was not copied to be deleted.
- Fixed bug that caused gsutil to use GET for ls -L requests. It now uses HEAD
  for ls -L requests, which is more efficient and faster.
- Fixed bug that caused gsutil not to preserve metadata during
  copy-in-the-cloud.
- Fixed bug that prevented setacl command from allowing DisplayName's in ACLs.
- Fixed bug that caused gsutil/boto to suppress consecutive slashes in path
  names.
- Fixed spec-non-compliant URI construction for resumable uploads.
- Fixed bug that caused rm -f not to work.
- Fixed UnicodeEncodeError that happened when redirecting gsutil ls output
  to a file with non-ASCII object names.

Other Changes
-------------

- UserAgent sent in HTTP requests now includes gsutil version number and OS
  name.
- Starting with this release users are able to get individual named releases
  from version-named objects: gs://pub/gsutil_<version>.tar.gz
  and gs://pub/gsutil_<version>.zip. The version-less counterparts
  (gs://pub/gsutil.tar.gz and gs://pub/gsutil.zip) will contain the latest
  release. Also, the gs://pub bucket is now publicly readable (so, anyone
  can list its contents).


Release 2.0 (release-date: 2012-01-13)
======================================

New Features
------------

- Support for for two new installation modes: enterprise and RPM.
  Customers can now install gsutil one of three ways:
  - Individual user mode (previously the only available mode): unpacking from
    a gzipped tarball (gs://pub/gsutil.tar.gz) or zip file
    (gs://pub/gsutil.zip) and running the gsutil command in place in the
    unpacked gsutil directory.
  - Enterprise mode (new): unpacking as above, and then running the setup.py
    script in the unpacked gsutil directory. This allows a systems
    administrator to install gsutil in a central location, using the Python
    distutils facility. This mode is supported only on Linux and MacOS.
  - RPM mode (new). A RedHat RPM can be built from the gsutil.spec.in file
    in the unpacked gsutil directory, allowing it to be installed as part of
    a RedHat build.

- Note: v2.0 is the first numbered gsutil release. Previous releases
  were given timestamps for versions. Numbered releases enable downstream
  package builds (like RPMs) to define dependencies more easily.
  This is also the first version where we began including release notes.
