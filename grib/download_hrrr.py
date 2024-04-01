import argparse
import datetime
import io
import os.path
import shutil
import subprocess
import platform
import boto3 as boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

REGIONS = [
    {'name': 'new-england',
     'nw': {'lat': 42, 'lon': -72},
     'se': {'lat': 41, 'lon': -70}},
    {'name': 'san-francisco',
     'nw': {'lat': 38, 'lon': -123.3},
     'se': {'lat': 36.5, 'lon': -121.5}},
    {'name': 'coastal-cup',
     'nw': {'lat': 38, 'lon': -123.3},
     'se': {'lat': 33, 'lon': -120.}},
]

if platform.system() == 'Darwin':
    WGRIB_BIN = os.path.expanduser('bin/osx/wgrib2')
else:
    WGRIB_BIN = '/usr/local/bin/wgrib2'

NOAA_HRRR_BUCKET_NAME = 'noaa-hrrr-bdp-pds'
OUTPUT_GRIB_BUCKET_NAME = 'com.gybetime.grib'


def decode_record(t):
    return {
        'start': int(t[1]),
        'type': t[3],
        'height': t[4]
    }


def parse_grib_index(grib_index):
    records = []
    for line in io.StringIO(grib_index):
        t = line.split(':')
        records.append(decode_record(t))
    # Add the end of record information
    for i in range(0, len(records) - 1):
        records[i]['end'] = records[i + 1]['start'] - 1
    return records


def download_grib_time_slice(s3, grib_name, work_dir, height_filter, type_filter):

    # Download GRIB index file
    grib_idx_name = grib_name + '.idx'
    try:
        resp = s3.get_object(Bucket=NOAA_HRRR_BUCKET_NAME, Key=grib_idx_name)
        grib_index = resp['Body'].read().decode("utf-8")

        # Parse index file
        records = parse_grib_index(grib_index)

        # Download desired records of GRIB file
        local_grib_name = os.path.expanduser(work_dir + os.sep + grib_name.replace('/', '_'))
        with open(local_grib_name, 'wb') as gf:
            for record in records:
                if record['height'] in height_filter and record['type'] in type_filter:
                    start_byte = record["start"]
                    stop_byte = record["end"]
                    print(f'Downloading range {start_byte} {stop_byte} from s3://{NOAA_HRRR_BUCKET_NAME}/{grib_name} ...')
                    resp = s3.get_object(Bucket=NOAA_HRRR_BUCKET_NAME, Key=grib_name, Range='bytes={}-{}'.format(start_byte,
                                                                                                                 stop_byte))
                    res = resp['Body'].read()
                    gf.write(res)
            print(f'{local_grib_name} created.')

            return local_grib_name

    except ClientError as ex:
        if ex.response['Error']['Code'] == 'NoSuchKey':
            print(f'GRIB {grib_name} not available on the server')
        else:
            return None

    return None


def extract_grib_region(grib_name, region):
    t = grib_name.split('.')
    small_local_grib_name = '.'.join(t[0:-1]) + '.small.' + t[-1]

    print(f'Extract small grib to {small_local_grib_name}')
    lon_bounds = f'{region["nw"]["lon"]}:{region["se"]["lon"]}'
    lat_bounds = f'{region["se"]["lat"]}:{region["nw"]["lat"]}'
    cmd_args = [WGRIB_BIN, grib_name,
                '-small_grib', lon_bounds, lat_bounds, small_local_grib_name]
    subprocess.run(cmd_args)

    return small_local_grib_name


def get_most_recent_grib(work_dir, height_filter, type_filter):
    run_utc = datetime.datetime.now(datetime.timezone.utc)
    # Find the most recent HRRR GRIB file
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    found = False
    max_days = 7
    while True:
        grib_dir = f'hrrr.{run_utc.year:04d}{run_utc.month:02d}{run_utc.day:02d}/conus'
        # Check if bucket contains this directory
        try:
            print(f'Checking {grib_dir}')
            resp = s3.list_objects_v2(Bucket=NOAA_HRRR_BUCKET_NAME, Prefix=grib_dir)
            if 'Contents' in resp:
                found = True
                break
            else:
                run_utc = run_utc - datetime.timedelta(days=1)
                max_days -= 1
                if max_days == 0:
                    break
        except ClientError as ex:
            if ex.response['Error']['Code'] == 'NoSuchKey':
                print(f'GRIB {grib_dir} not available on the server')
                # Try the previous day
                run_utc = run_utc - datetime.timedelta(days=1)
                max_days -= 1
                if max_days == 0:
                    break
            else:
                raise

    if not found:
        print(f'No HRRR GRIB found in the last {max_days} days')
        return None

    print(f'Found the most recent HRRR GRIB {grib_dir}')
    # Get list of files in the directory
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=NOAA_HRRR_BUCKET_NAME, Prefix=grib_dir + '/hrrr')
    gribs = []
    for page in pages:
        for obj in page['Contents']:
            grib_name = obj["Key"]
            if 'wrfsfc' in grib_name:
                gribs.append(grib_name)

    gribs = sorted(gribs, reverse=True)

    # Find most recent F48 GRIB
    f48_run_hour = None
    for grib in gribs:
        if 'f48' in grib:
            t = grib.split('.')
            f48_run_hour = int(t[2][1:3])
            print(f'F48 {grib} run hour {f48_run_hour}')
            break

    # Find most recent F18 GRIB
    f18_run_hour = None
    for grib in gribs:
        if 'f18' in grib:
            t = grib.split('.')
            f18_run_hour = int(t[2][1:3])
            print(f'F18 {grib} run hour {f18_run_hour}')
            break

    if f48_run_hour is None:
        print('F48 GRIB not found')
        return None

    # Build list of GRIBs to download
    grib_list = []
    first_fcst_hour = run_utc.hour - f18_run_hour
    if f18_run_hour == f48_run_hour:
        for i in range(first_fcst_hour, 49):
            grib_name = grib_dir + '/' + f'hrrr.t{f48_run_hour:02d}z.wrfsfcf{i:02d}.grib2'
            grib_list.append(grib_name)
    else:
        for i in range(first_fcst_hour, 19):
            grib_name = grib_dir + '/' + f'hrrr.t{f18_run_hour:02d}z.wrfsfcf{i:02d}.grib2'
            grib_list.append(grib_name)
        first_fcst_hour = f18_run_hour - f48_run_hour + 19
        for i in range(first_fcst_hour, 49):
            grib_name = grib_dir + '/' + f'hrrr.t{f48_run_hour:02d}z.wrfsfcf{i:02d}.grib2'
            grib_list.append(grib_name)

    out_gribs = []
    for region in REGIONS:
        region_name = region['name']
        out_grib_name = (work_dir + os.sep +
                         f'hrrr-{region_name}-{run_utc.year:04d}-{run_utc.month:02d}-{run_utc.day:02d}-{f18_run_hour:02d}.grib2')
        out_grib = open(out_grib_name, 'wb')
        out_gribs.append((out_grib_name, out_grib))
        print(f'Creating {out_grib_name} ...')

    # Iterate over time
    for idx, grib in enumerate(grib_list):
        print(f'Download {idx + 1} {grib}')
        grib_time_slice = download_grib_time_slice(s3, grib, work_dir, height_filter, type_filter)

        if grib_time_slice is not None:
            # For each time slice extract the region
            for reg_idx, region in enumerate(REGIONS):
                region_grib_name = extract_grib_region(grib_time_slice, region)

                in_grib = open(region_grib_name, 'rb')
                out_grib = out_gribs[reg_idx][1]
                shutil.copyfileobj(in_grib, out_grib)
                in_grib.close()

                print(f'Removing {region_grib_name} ...')
                os.unlink(region_grib_name)

            print(f'Removing {grib_time_slice} ...')
            os.unlink(grib_time_slice)

    for reg_idx, region in enumerate(REGIONS):
        out_gribs[reg_idx][1].close()
        print(f'{out_gribs[reg_idx][0]} created.')

    return out_gribs


def download_hrrr():
    work_dir = '/tmp'
    height_filter = ['10 m above ground']
    type_filter = ['UGRD', 'VGRD']
    out_gribs = get_most_recent_grib(work_dir, height_filter, type_filter)

    # Upload the GRIB files to the output bucket
    grib_list_name = work_dir + os.sep + 'grib-list.txt'

    with open(grib_list_name, 'wt') as grib_list:
        s3 = boto3.client('s3')
        for reg_idx, region in enumerate(REGIONS):
            out_gribs[reg_idx][1].close()
            grib_name = out_gribs[reg_idx][0]
            with open(grib_name, 'rb') as f:
                # Uploading the GRIB file to the output bucket
                print(f'Uploading {grib_name} to s3://{OUTPUT_GRIB_BUCKET_NAME}/{os.path.basename(grib_name)} ...')
                s3.upload_fileobj(f, OUTPUT_GRIB_BUCKET_NAME, os.path.basename(grib_name))
                grib_list.write(f'{os.path.basename(grib_name)}\n')

    grib_list.close()
    with open(grib_list_name, 'rb') as f:
        print(f'Uploading {grib_list_name} to s3://{OUTPUT_GRIB_BUCKET_NAME}/{os.path.basename(grib_list_name)} ...')
        s3.upload_fileobj(f, OUTPUT_GRIB_BUCKET_NAME, os.path.basename(grib_list_name))


def handler(event, context):
    print(event)
    print(context)
    download_hrrr()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--profile', help="AWS profile to use", required=False)
    args = parser.parse_args()
    boto3.setup_default_session(profile_name=args.profile)
    download_hrrr()
