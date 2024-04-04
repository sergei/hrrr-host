import argparse
import datetime
import os

import requests

BASE_URL_HRRR_URL = 'http://com.gybetime.grib.s3-website-us-east-1.amazonaws.com/'
HRRR_LIST = 'grib-list.txt'


def get_gribs(param):
    out_dir = os.path.expanduser(param.out_dir)

    print(f'Tide Tech API key: {param.tide_tech_api}')
    regions = []
    if param.region_list:
        if isinstance(param.region_list, list):
            regions = param.region_list
        else:
            regions.append(param.region_list)
        print(f'Regions: {regions}')

        # Download HRRR GRIB files
        get_hrrr_gribs(regions, out_dir)
    else:
        print('No regions specified. Skipping HRRR download.')

    # Download current tide data
    if param.tide_tech_api:
        get_tide_data(param.tide_tech_api, out_dir)
    else:
        print('No Tide Tech API key specified. Skipping tide data download.')


def get_tide_data(tide_tech_api, out_dir):
    tide_tech_url = (f'https://api.tidetech.org/v1/dataset/san-francisco-currents/data/'
                     f'?api_key={tide_tech_api}&file_format=grb')
    now = datetime.datetime.now()
    out_file = os.path.join(out_dir, f'{now.strftime("%Y-%m-%d-%H")}-tide.grb')
    print(f'Downloading {tide_tech_url} to {out_file} ...')
    response = requests.get(tide_tech_url)
    if response.status_code == 200:
        with open(out_file, 'wb') as f:
            f.write(response.content)
        print(f'{out_file} created.')
    else:
        print(f'Failed to download {tide_tech_url}')


def get_hrrr_gribs(regions, out_dir):
    # Download HRRR GRIB list
    hrrr_list_url = BASE_URL_HRRR_URL + HRRR_LIST
    print(f'Downloading {hrrr_list_url} ...')
    response = requests.get(hrrr_list_url)
    if response.status_code == 200:
        lines = response.text.split('\n')
        for line in lines:
            if len(regions) == 0 or any(region in line for region in regions):
                hrrr_url = BASE_URL_HRRR_URL + line
                out_file = os.path.join(out_dir, line)
                print(f'Downloading {hrrr_url} to {out_file} ...')
                response = requests.get(hrrr_url)
                if response.status_code == 200:
                    with open(out_file, 'wb') as f:
                        f.write(response.content)
                    print(f'{out_file} created.')
                else:
                    print(f'Failed to download {hrrr_url}')
    else:
        print(f'Failed to download {hrrr_list_url}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--tide-tech-api', help="Tide Tech API key", required=False)
    parser.add_argument('-o', '--out-dir', help="Output directory", required=True)
    parser.add_argument('-l', '--region-list',  nargs='+', help="List of regions to download",
                        required=False)

    get_gribs(parser.parse_args())
