#!/bin/sh

# Utility command to generate an rpm package file for gsutil.
# This tool takes no arguments and leaves the resulting rpm package
# file at this location under your home rpmbuild tree: 
# $HOME/rpmbuild/RPMS/noarch/gsutil-$VERSION-<N>.noarch.rpm
# where <N> is the build number.

SPEC_FILE_IN=gsutil.spec.in
SPEC_FILE=gsutil.spec

# Pre-process the rpm spec file.
python pkg_util.py

# Get package name and version from spec file.
NAME=`awk <$SPEC_FILE '/^Name:/ {print $2}'`
if [ "$NAME" = "" ]
then
  echo "Error: Name variable not set properly in $SPEC_FILE."
  exit 1
fi

VERSION=`awk <$SPEC_FILE '/^Version:/ {print $2}'`
ROOT=$NAME-$VERSION
STAGING_DIR=$HOME/rpmbuild/SOURCES/$ROOT

# Update VERSION file to reflect current version.
echo $VERSION >VERSION

# Make sure STAGING_DIR is set so we don't do a recursive rm below
# on an indeterminate location.
if [ "$STAGING_DIR" = "" ]
then
  echo "Can't proceed - STAGING_DIR not set properly."
  exit 1
fi

# Create staging dir and copy package files there, filtering .svn dirs 
# and .pyc files.
rm -rf $STAGING_DIR
mkdir -p $STAGING_DIR
find . -print | grep -v "\.svn" | grep -v "\.pyc$" | cpio -pud $STAGING_DIR

# Generate archive from staging area contents, then clean up staging area.
CUR_DIR=$PWD
cd $STAGING_DIR/..
zip -r $ROOT.zip $ROOT

cd $CUR_DIR
rm -rf $STAGING_DIR

# New build RPM package based on generated spec file and archive contents.
rpmbuild -ba gsutil.spec

