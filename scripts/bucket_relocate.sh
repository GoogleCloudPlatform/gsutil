#!/bin/bash
# Copyright 2013 Google Inc. All Rights Reserved.
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

function Usage {
  cat << EOF
bucket_relocate - relocates buckets in Google Cloud Storage

This script can be used to migrate one or more buckets to a different
location and/or storage class. It operates in two stages: In stage 1, a
temporary bucket is created in the new location/storage class corresponding
to each bucket being migrated, and data are copied from the original to the
new bucket(s). In stage 2 any newly created data are copied from the original to
the temporary bucket(s), the original buckets are deleted and recreated in the
new location/storage class, data are copied from the temporary to the re-created
bucket(s), and the temporary bucket(s) deleted. Stage 1 can take a long time
because it copies all data via the local machine (because copy-in-the-cloud
isn't support spanning locations or storage classes); stage 2 should run quickly
(because it uses copy-in-the-cloud), unless a large amount of data was added
to the bucket while stage 1 was running. You should ensure that no reads or
writes occur to your bucket during the brief period while stage 2 runs.

To ensure that all data are correctly copied from the source to the temporary
bucket, we recommend running stage 1 first, and then comparing the source and
temporary buckets by executing:

  gsutil ls -L gs://yourbucket > ls.1
  gsutil ls -L gs://yourbucket-relocate > ls.2
  # Use some program that visually highlights diffs, such as:
  vimdiff ls.1 ls.2

Starting conditions:
You must have at least version 4.0 of bash and version 3.35 of gsutil installed,
with credentials (in your.boto config file) that have FULL_CONTROL access to all
buckets and objects being migrated. If this script is run using credentials that
lack these permissions it will fail part-way through, at which point you will
need to change the ACLs of the affected objects and re-run the script. (The
script keeps track of what it has completed, so you can re-run it after an
interruption or problem.) If you specify the -v option the script will check all
permissions before starting the migration (which takes time, because it performs
a HEAD on each object as well as a GET on the object's ?acl subresource). If you
do use the -v option it's possible the script will find no problems, begin the
migration, and then encounter permission problems because of objects that are
uploaded after the script begins. If that happens the script will fail part-way
through and you will need to change the object ACLs and re-run the script.

If you need to change ACLs you can do so using a command like:

  gsutil acl ch -u scriptuser@gmail.com:FC gs://bucket/object1 gs://bucket/object2 ...

where scriptuser@agmail.com is the identity for which your credentials are
configured.

Caveats:
1) If an object is deleted from the original bucket after it has been processed
   in stage 1, that object will not be deleted during stage 2.
2) If an object is overwritten after it has been processed in stage 1, that
   change will not be re-copied during stage 2.
3) Object change notification configuration is not preserved by this migration
   script.
4) Restored objects in versioned buckets will preserve the version ordering but
   not version numbers. For example, if the original bucket contained:
     gs://bucket/obj#1340448460830000 and gs://bucket/obj#1350448460830000
   the restored bucket might have objects with these versions:
     gs://bucket/obj#1360448460830000 and gs://bucket/obj#1370448460830000
   Beware of this caveat if you have code that stores the version-ful name
   of objects (e.g., in a database).
5) Buckets with names longer than 55 characters can not be migrated.
   This is because the resulting temporary bucket name will be too long (>63
   characters).
6) Since this script stores state in ~/bucketrelo/. Please do not remove this
   directory until the scripts have completed successfully.

If your application overwrites or deletes objects, we recommend disabling all
writes while running both stages.

Usage:
   bucket_relocate.sh STAGE [OPTION]... bucket...

Examples:
   bucket_relocate.sh -2 gs://mybucket1 gs://mybucket2

STAGE
   The stage determines what stage should be executed:
   -1            run stage 1 - during this stage users can still add objects to
                 the bucket(s) being migrated.
   -2            run stage 2 - during this stage no users should add or modify
                 any objects in the bucket(s) being migrated.
   -A            run stage 1 and stage 2 back-to-back - use this option if you
                 are guaranteed that no users will be making changes to the
                 bucket throughout the entire process.
    Please note that during both stages users should not delete or overwrite
    objects in the buckets being migrated, because these changes will not be
    detected.

OPTIONS
   -?            show this usage information.

   -c <class>    sets the storage class of the destination bucket.
                 Example storage classes:
                 S - Standard (default)
                 DRA - Durable Reduced Availability storage.

   -l <location> sets the location of the destination bucket.
                 Example locations:
                 US - United States (default)
                 EU - European Union

    -v           Verify that the credentials being used have write access to all
                 buckets being migrated and read access to all objects within
                 those buckets.

Multiple buckets can be specified if more than one bucket needs to be
relocated. This can be done as follows:

   bucket_relocate.sh -A gs://bucket01 gs://bucket02 gs://bucket03

To relocate all buckets in a given project, you could do the following:

   gsutil ls -p project-id | xargs bucket_relocate.sh -A -c DRA -l EU

EOF
}

buckets=()
tempbuckets=()
stage=-1
location=''
class=''
extra_verification=false

basedir=~/bucketrelo
manifest=$basedir/relocate-manifest-
steplog=$basedir/relocate-step-
debugout=$basedir/relocate-debug-$(date -d "today" +"%Y%m%d%H%M%S").log
permcheckout=$basedir/relocate-permcheck-
metadefacl=$basedir/relocate-defacl-for-
metawebcfg=$basedir/relocate-webcfg-for-
metalogging=$basedir/relocate-logging-for-
metacors=$basedir/relocate-cors-for-
metavers=$basedir/relocate-vers-for-
metalifecycle=$basedir/relocate-lifecycle-for-

# This script requires Bash 4.0 or higher
if [ ${BASH_VERSION:0:1} -lt 4 ]; then
  echo "This script requires bash version 4 or higher." 1>&2;
  exit 1
fi

# Create the working directory where we store all the temporary state.
if [ ! -d $basedir ]; then
  mkdir $basedir
  if [ $? -ne 0 ]; then
    echo "Could not create $basedir."
    exit 1
  fi
fi


function ParallelIfNoVersioning() {
  versioning=`$gsutil versioning get $1 | head -1`
  if [ "$versioning" == '' ]; then
    EchoErr "Failed to retrieve versioning information for $1"
    exit 1
  fi
  vpos=$((${#src} + 2))
  versioning=${versioning:vpos}
  if [ "$versioning" == 'Enabled' ]; then
    echo "$src has versioning enabled, so we have to copy all objects "\
         "sequentially, to preserve the object version ordering."
    parallel_if_no_versioning=""
  else
    parallel_if_no_versioning="-m"
  fi
}

function DeleteBucketWithRetry() {
  # Add some retries as occasionally the object deletes need to filter
  # through the system.
  attempt=0
  success=false
  while [ $success == false ]; do
    result=$(($gsutil -m rm -Ra $1/*) 2>&1)
    if [ $? -ne 0 ]; then
      if [[ "$result" != *No\ URIs\ matched* ]]; then
        EchoErr "Failed to delete the objects from bucket: $1"
        exit 1
      fi
    fi
    result=$(($gsutil rb $1) 2>&1)
    if [ $? -ne 0 ]; then
      if [[ "$result" == *code=BucketNotEmpty* ]]; then
        attempt=$(( $attempt+1 ))
        if [ $attempt -gt 30 ]; then
          EchoErr "Failed to remove the bucket: $1"
          exit 1
        else
          EchoErr "Waiting for buckets to empty."
          sleep 10s
        fi
      else
        EchoErr "Failed to remove the bucket: $1"
        exit 1
      fi
    else
      success=true
    fi
  done
}

function EchoErr() {
  # echo the function parameters to stderr.
  echo "$@" 1>&2;
  echo "ERROR -- $1" >> $debugout
}

function LastStep() {
  short_name=${1:5}
  if [ -f $steplog$short_name ]; then
    echo `cat $steplog$short_name`
  else
    echo 0
  fi
}

function LogStepStart() {
  echo $1
  echo "START -- $1" >> $debugout
}

function LogStepEnd() {
  # $1 = bucket name, $2 = step number
  short_name=${1:5}
  echo $2 > $steplog$short_name
  echo "END -- $1" >> $debugout
}

function CheckBucketExists() {
  # Strip out gs://, so can use bucket name as part of filename.
  bucket=`echo $1 | sed 's/.....//'`
  # Redirect stderr so we can check for permission denied.
  $gsutil versioning get $1 &> $basedir/bucketcheck.$bucket
  if [ $? -eq 0 ]; then
    result="Exist"
  else
    grep -q AccessDenied $basedir/bucketcheck.$bucket
    if [ $? -eq 0 ]; then
      result="AccessDenied"
    else
      result="NotExist"
    fi
  fi
  cat $basedir/bucketcheck.$bucket >> $debugout
  rm $basedir/bucketcheck.$bucket
  echo $result
}

# Parse command line arguments
while getopts ":?12Ac:l:v" opt; do
  case $opt in
    A)
      # Using -A will make stage 1 and 2 run back-to-back
      if [ $stage != -1 ]; then
        EchoErr "Only a single stage can be set."
        exit 1
      fi
      stage=0
      ;;
    1)
      if [ $stage != -1 ]; then
        EchoErr "Only a single stage can be set."
        exit 1
      fi
      stage=1
      ;;
    2)
      if [ $stage != -1 ]; then
        EchoErr "Only a single stage can be set."
        exit 1
      fi
      stage=2
      ;;
    c)
      # Sets the storage class, such as S (for Standard) or DRA (for Durable
      # Reduced Availability)
      if [ "$class" != '' ]; then
        EchoErr "Only a single class can be set."
        exit 1
      fi
      class=$OPTARG
      ;;
    l)
      # Sets the location of the bucket. For example: US or EU
      if [ "$location" != '' ]; then
        EchoErr "Only a single location can be set."
        exit 1
      fi
      location=$OPTARG
      ;;
    v)
      extra_verification=true
      ;;
    ?)
      Usage
      exit 0
      ;;
    \?)
      EchoErr "Invalid option: -$OPTARG"
      exit 1
      ;;
  esac
done

shift $(($OPTIND - 1))
while test $# -gt 0; do
  # Buckets must have the gs:// prefix.
  if [ ${#1} -lt 6 ] || [ "${1:0:5}" != 'gs://' ]; then
    EchoErr "$1 is not a supported bucket name. Bucket names must start with gs://"
    exit 1
  fi
  # Bucket names must be <= 55 characters long
  max_length=$(( 55 + 5 ))  # + 5 for the prefix
  if [ ${#1} -gt $max_length ]; then
    EchoErr "The name of the bucket ($1) is too long."
    exit 1
  fi
  buckets=("${buckets[@]}" ${1%/})
  tempbuckets=("${tempbuckets[@]}" ${1%/}-relocate)
  shift
done

num_buckets=${#buckets[@]}
if [ $num_buckets -le 0 ]; then
  Usage
  exit 1
fi
if [ $stage == -1 ]; then
  EchoErr "Stage not specified. Please specify either -A (for all), -1, or -2."
  exit 1
fi
if [[ "$location" == '' ]]; then
  location='US'
fi
if [[ "$class" == '' ]]; then
  class='S'
fi

# Display a summary of the options
if [ $stage == 0 ]; then
  echo "Stage:         All stages"
else
  echo "Stage:         $stage"
fi
echo "Location:      $location"
echo "Storage class: $class"
echo "Bucket(s):     ${buckets[@]}"

# Check for prerequisites
# 1) Check to see if gsutil is installed
gsutil=`which gsutil`
if [ "$gsutil" == '' ]; then
  EchoErr "gsutil was not found. Please install it from https://developers.google.com/storage/docs/gsutil_install"
  exit 1
fi

# 2) Check if gsutil is configured correctly by attempting to list up through
#    the first bucket from a gsutil ls. We can safely assume there is at least
#    one bucket otherwise we would not be running this script. Redirect stderr
#    to /dev/null so if user has a large number of buckets a Broken Pipe error
#    isn't output.
test_bucket=`$gsutil ls 2> /dev/null | head -1`
if [ "$test_bucket" == '' ]; then
  EchoErr "gsutil does not seem to be configured. Please run gsutil config."
  exit 1
fi

# 3) Checking gsutil version
gsutil_version=`$gsutil version`
if [ $? -ne 0 ]; then
  EchoErr "Failed to get version information for gsutil."
  exit 1
fi
major=${gsutil_version:15:1}
minor=${gsutil_version:17:2}
if [ $major -lt 3 ] || ( [ $major -eq 3 ] && [ $minor -lt 35 ] ); then
  EchoErr "Incorrect version of gsutil. Need 3.35 or greater. Have: $gsutil_version"
  exit 1
fi

function Stage1 {
  echo 'Now executing stage 1...'

  # For each bucket, do some verifications:
  for i in ${!buckets[*]}; do
    bucket=${buckets[$i]}
    src=$bucket

    # Verify that the source bucket exists.
    if [ `LastStep "$src"` -eq 0 ]; then
      LogStepStart "Step 1: ($src) - Verify the bucket exists."
      result=`CheckBucketExists $src`
      if [ "$result" == "AccessDenied" ]; then
        EchoErr "Validation check failed: The account running this script does not have permission to access bucket $bucket"
        exit 1
      elif [ "$result" == "NotExist" ]; then
        EchoErr "Validation check failed: The specified bucket does not exist: $bucket"
        exit 1
      fi
      LogStepEnd $src 1
    fi

    # Verify that we can read all the objects.
    if [ `LastStep "$src"` -eq 1 ]; then
      if $extra_verification ; then
        LogStepStart "Step 2: ($src) - Check object permissions. This may take a while..."
        # The following will attempt to HEAD each object in the bucket, to
        # ensure the credentials running this script have read access to all data
        # being migrated.
        short_name=${src:5}
        $gsutil ls -L $src/** &> $permcheckout$short_name
        grep -q 'ACCESS DENIED' $permcheckout$short_name
        if [ $? -eq 0 ]; then
          EchoErr "Validation failed: Access denied reading an object from $src."
          EchoErr "Check the log file ($permcheckout$short_name) for more details."
          exit 1
        fi
        LogStepEnd $src 2
      else
        LogStepStart "Step 2: ($src) - Skipping object permissions check."
        LogStepEnd $src 2
      fi
    fi

    # Verify WRITE access to the bucket.
    if [ `LastStep "$src"` -eq 2 ]; then
      LogStepStart "Step 3: ($src) - Checking write permissions."
      random_name="relocate_check_`cat /dev/urandom |\
          LANG=C tr -dc 'a-zA-Z' | head -c 60`"
      echo 'relocate access check' | gsutil cp - $src/$random_name &>> $debugout
      if [ $? -ne 0 ]; then
        EchoErr "Validation check failed: Access denied writing to $src."
        exit 1
      fi

      # Remove the temporary file.
      gsutil rm -a $src/$random_name &>> $debugout
      if [ $? -ne 0 ]; then
        EchoErr "Validation failed: Could not delete temporary object: $src/$random_name"
        EchoErr "Check the log file ($debugout) for more details."
        exit 1
      fi
      LogStepEnd $src 3
    fi
  done

  # For each bucket, do the processing...
  for i in ${!buckets[*]}; do
    src=${buckets[$i]}
    dst=${tempbuckets[$i]}
    bman=$manifest${src:5}  # The manifest contains the short name of the bucket

    # verify that the bucket does not yet exist and create it in the
    # correct location with the correct storage class
    if [ `LastStep "$src"` -eq 3 ]; then
      LogStepStart "Step 4: ($src) - Create a temporary bucket ($dst)."
      dst_exists=`CheckBucketExists $dst`
      if [ "$dst_exists" == "Exist" ]; then
        EchoErr "The bucket $dst already exists."
        exit 1
      else
        $gsutil mb -l $location -c $class $dst
        if [ $? -ne 0 ]; then
          EchoErr "Failed to create the bucket: $dst"
          exit 1
        fi
      fi
      LogStepEnd $src 4
    fi

    if [ `LastStep "$src"` -eq 4 ]; then
      # If the source has versioning, so should the temporary bucket.
      LogStepStart "Step 5: ($src) - Turn on versioning on the temporary bucket (if needed)."
      versioning=`$gsutil versioning get $src | head -1`
      if [ "$versioning" == '' ]; then
        EchoErr "Failed to retrieve versioning information for $src"
        exit 1
      fi
      vpos=$((${#src} + 2))
      versioning=${versioning:vpos}
      if [ "$versioning" == 'Enabled' ]; then
        # We need to turn this on when we are copying versioned objects.
        $gsutil versioning set on $dst
        if [ $? -ne 0 ]; then
          EchoErr "Failed to turn on versioning on the temporary bucket: $dst"
          exit 1
        fi
      fi
      LogStepEnd $src 5
    fi

    # Copy the objects from the source bucket to the temp bucket
    if [ `LastStep "$src"` -eq 5 ]; then
      LogStepStart "Step 6: ($src) - Copy objects from source to the temporary bucket ($dst) via local machine."
      ParallelIfNoVersioning $src
      $gsutil $parallel_if_no_versioning cp -R -p -L $bman -D $src/* $dst/
      if [ $? -ne 0 ]; then
        EchoErr "Failed to copy objects from $src to $dst."
        exit 1
      fi
      LogStepEnd $src 6
    fi

    # Backup the metadata for the bucket
    if [ `LastStep "$src"` -eq 6 ]; then
      short_name=${src:5}
      LogStepStart "Step 7: ($src) - Backup the bucket metadata."
      $gsutil defacl get $src > $metadefacl$short_name
      if [ $? -ne 0 ]; then
        EchoErr "Failed to backup the default ACL configuration for $src"
        exit 1
      fi
      $gsutil web get $src > $metawebcfg$short_name
      if [ $? -ne 0 ]; then
        EchoErr "Failed to backup the web configuration for $src"
        exit 1
      fi
      $gsutil logging get $src > $metalogging$short_name
      if [ $? -ne 0 ]; then
        EchoErr "Failed to backup the logging configuration for $src"
        exit 1
      fi
      $gsutil cors get $src > $metacors$short_name
      if [ $? -ne 0 ]; then
        EchoErr "Failed to backup the CORS configuration for $src"
        exit 1
      fi
      $gsutil versioning get $src > $metavers$short_name
      if [ $? -ne 0 ]; then
        EchoErr "Failed to backup the versioning configuration for $src"
        exit 1
      fi
      versioning=`cat $metavers$short_name | head -1`
      $gsutil lifecycle get $src > $metalifecycle$short_name
      if [ $? -ne 0 ]; then
        EchoErr "Failed to backup the lifecycle configuration for $src"
        exit 1
      fi
      LogStepEnd $src 7
    fi


  done

  if [ $stage == 1 ]; then
    # Only show this message if we are not running both stages back-to-back.
    echo 'Stage 1 complete. Please ensure no reads or writes are occurring to your bucket(s) and then run stage 2.'
    echo 'At this point, you can verify that the objects were correctly copied by doing:'
    echo '    gsutil ls -L gs://yourbucket > ls.1'
    echo '    gsutil ls -L gs://yourbucket-relocate > ls.2'
    echo '    # Use some program that visually highlights diffs:'
    echo '    vimdiff ls.1 ls.2'
  fi
}

function Stage2 {
  echo 'Now executing stage 2...'

  # Make sure all the buckets are at least at step #5
  for i in ${!buckets[*]}; do
    src=${buckets[$i]}
    dst=${tempbuckets[$i]}

    if [ `LastStep "$src"` -lt 7 ]; then
      EchoErr "Relocation for bucket $src did not complete stage 1. Please rerun stage 1 for this bucket."
      exit 1
    fi
  done

  # For each bucket, do the processing...
  for i in ${!buckets[*]}; do
    src=${buckets[$i]}
    dst=${tempbuckets[$i]}
    bman=$manifest${src:5}

    # Catch up with any new files.
    if [ `LastStep "$src"` -eq 7 ]; then
      LogStepStart "Step 8: ($src) - Catch up any new objects that weren't copied."
      ParallelIfNoVersioning $src
      $gsutil $parallel_if_no_versioning cp -R -p -L $bman -D $src/* $dst/
      if [ $? -ne 0 ]; then
        EchoErr "Failed to copy any new objects from $src to $dst"
        exit 1
      fi
      LogStepEnd $src 8
    fi

    # Remove the old src bucket
    if [ `LastStep "$src"` -eq 8 ]; then
      LogStepStart "Step 9: ($src) - Delete the source bucket and objects."
      DeleteBucketWithRetry $src
      LogStepEnd $src 9
    fi

    if [ `LastStep "$src"` -eq 9 ]; then
      LogStepStart "Step 10: ($src) - Recreate the original bucket."
      $gsutil mb -l $location -c $class $src
      if [ $? -ne 0 ]; then
        EchoErr "Failed to recreate the bucket: $src"
        exit 1
      fi
      LogStepEnd $src 10
    fi

    if [ `LastStep "$src"` -eq 10 ]; then
      short_name=${src:5}
      LogStepStart "Step 11: ($src) - Restore the bucket metadata."

      # defacl
      $gsutil defacl set $metadefacl$short_name $src
      if [ $? -ne 0 ]; then
        EchoErr "Failed to set the default ACL configuration on $src"
        exit 1
      fi

      # webcfg
      page_suffix=`cat $metawebcfg$short_name |\
          grep -o "<MainPageSuffix>.*</MainPageSuffix>" |\
          sed -e 's/<MainPageSuffix>//g' -e 's/<\/MainPageSuffix>//g'`
      if [ "$page_suffix" != '' ]; then page_suffix="-m $page_suffix"; fi
      error_page=`cat $metawebcfg$short_name |\
          grep -o "<NotFoundPage>.*</NotFoundPage>" |\
          sed -e 's/<NotFoundPage>//g' -e 's/<\/NotFoundPage>//g'`
      if [ "$error_page" != '' ]; then error_page="-e $error_page"; fi
      $gsutil web set $page_suffix $error_page $src
      if [ $? -ne 0 ]; then
        EchoErr "Failed to set the website configuration on $src"
        exit 1
      fi

      # logging
      log_bucket=`cat $metalogging$short_name |\
          grep -o "<LogBucket>.*</LogBucket>" |\
          sed -e 's/<LogBucket>//g' -e 's/<\/LogBucket>//g'`
      if [ "$log_bucket" != '' ]; then log_bucket="-b gs://$log_bucket"; fi
      log_prefix=`cat $metalogging$short_name |\
          grep -o "<LogObjectPrefix>.*</LogObjectPrefix>" |\
          sed -e 's/<LogObjectPrefix>//g' -e 's/<\/LogObjectPrefix>//g'`
      if [ "$log_prefix" != '' ]; then log_prefix="-o $log_prefix"; fi
      if [ "$log_prefix" != '' ] && [ "$log_bucket" != '' ]; then
        $gsutil logging set on $log_bucket $log_prefix $src
        if [ $? -ne 0 ]; then
          EchoErr "Failed to set the logging configuration on $src"
          exit 1
        fi
      fi

      # cors
      $gsutil cors set $metacors$short_name $src
      if [ $? -ne 0 ]; then
        EchoErr "Failed to set the CORS configuration on $src"
        exit 1
      fi

      # versioning
      versioning=`cat $metavers$short_name | head -1`
      vpos=$((${#src} + 2))
      versioning=${versioning:vpos}
      if [ "$versioning" == 'Enabled' ]; then
        $gsutil versioning set on $src
        if [ $? -ne 0 ]; then
          EchoErr "Failed to set the versioning configuration on $src"
          exit 1
        fi
      fi

      # lifecycle
      $gsutil lifecycle set $metalifecycle$short_name $src
      if [ $? -ne 0 ]; then
        EchoErr "Failed to set the lifecycle configuration on $src"
        exit 1
      fi

      LogStepEnd $src 11
    fi

    if [ `LastStep "$src"` -eq 11 ]; then
      LogStepStart "Step 12: ($src) - Copy all objects back to the original bucket (copy in the cloud)."
      ParallelIfNoVersioning $src
      $gsutil $parallel_if_no_versioning cp -Rp $dst/* $src/
      if [ $? -ne 0 ]; then
        EchoErr "Failed to copy the objects back to the original bucket: $src"
        exit 1
      fi
      LogStepEnd $src 12
    fi

    if [ `LastStep "$src"` -eq 12 ]; then
      LogStepStart "Step 13: ($src) - Delete the temporary bucket ($dst)."
      DeleteBucketWithRetry $dst
      LogStepEnd $src 13
    fi
  done

  # Cleanup for each bucket
  for i in ${!buckets[*]}; do
    src=${buckets[$i]}
    dst=${tempbuckets[$i]}
    
    if [ `LastStep "$src"` -eq 13 ]; then
	  LogStepStart "Step 14: ($src) - Cleanup."
      ssrc=${src:5}  # short src
      mv $manifest$ssrc $manifest$ssrc.DONE
      mv $steplog$ssrc $steplog$ssrc.DONE
      if [ -f $permcheckout$ssrc ]; then
        mv $permcheckout$ssrc $permcheckout$ssrc.DONE
      fi
      mv $metadefacl$ssrc $metadefacl$ssrc.DONE
      mv $metawebcfg$ssrc $metawebcfg$ssrc.DONE
      mv $metalogging$ssrc $metalogging$ssrc.DONE
      mv $metacors$ssrc $metacors$ssrc.DONE
      mv $metavers$ssrc $metavers$ssrc.DONE
    fi

    LogStepStart "($src): Completed."
  done
  
  mv $debugout $debugout.DONE
}

if [ $stage == 0 ]; then
  Stage1
  Stage2
elif [ $stage == 1 ]; then
  Stage1
elif [ $stage == 2 ]; then
  Stage2
fi


