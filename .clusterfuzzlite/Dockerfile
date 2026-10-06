FROM gcr.io/oss-fuzz-base/base-builder-python:v1
COPY . $SRC/devin-internals-spec
WORKDIR devin-internals-spec
COPY .clusterfuzzlite/build.sh $SRC/build.sh
