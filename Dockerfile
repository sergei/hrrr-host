FROM ubuntu:20.04
# Prevent installer asking some questions
ARG DEBIAN_FRONTEND=noninteractive
# Let tzinfo know where we are
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
     build-essential \
     gfortran \
     python3.9 \
     python3-pip

RUN pip install boto3

RUN apt-get install -y curl cmake

RUN curl https://ftp.cpc.ncep.noaa.gov/wd51we/wgrib2/wgrib2.tgz -O \
    && tar xvzf wgrib2.tgz

# Necessary to build grib2
ENV CC=gcc
ENV FC=gfortran
RUN cd grib2 \
    && make

# Install wgrib2
RUN cp grib2/wgrib2/wgrib2 /usr/local/bin/wgrib2 \
    && rm -rf grib2 \
    && rm wgrib2.tgz \
    && wgrib2 -version || echo "done"

COPY download_hrrr.py /usr/local/bin/download_hrrr.py

CMD ["python3", "/usr/local/bin/download_hrrr.py"]
