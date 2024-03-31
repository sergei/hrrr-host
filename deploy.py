import argparse
import os
import zipfile
import boto3
from botocore.exceptions import ClientError, WaiterError

IGNORED_FILES = ['.DS_Store', '.git', '.idea', '__pycache__', 'lambda/bin/osx']


def deploy_stack(stack_name, parameters, session=None):
    template_file = stack_name + '.yaml'

    print('Loading AWS client  ...')
    if session is None:
        cf = boto3.resource('cloudformation')
        client = boto3.client('cloudformation')
    else:
        cf = session.resource('cloudformation')
        client = session.client('cloudformation')

    print('Looking for stack  %s ...' % stack_name)
    stack = cf.Stack(stack_name)
    stack_exists = False
    try:
        stack_id = stack.stack_id
        print('Found existing stack ', stack_id)
        stack_exists = True
    except ClientError:
        print("Stack doesn't exist")

    wait_for_update = True
    waiter_name = 'stack_create_complete'
    ok_status = 'CREATE_COMPLETE'
    try:
        if stack_exists:
            print('Trying to update stack %s  ...' % stack_name)
            stack.update(
                TemplateBody=open(template_file, 'r').read(),
                Capabilities=['CAPABILITY_IAM'],
                Parameters=parameters,
                UsePreviousTemplate=False
            )
            waiter_name = 'stack_update_complete'
            ok_status = 'UPDATE_COMPLETE'
        else:
            client.create_stack(
                StackName=stack_name,
                TemplateBody=open(template_file, 'r').read(),
                Capabilities=['CAPABILITY_IAM'],
                Parameters=parameters
            )
    except ClientError as e:
        print('Stack %s was not created / updated' % stack_name)
        print('error string=[%s]' % str(e))
        if 'No updates are to be performed' not in str(e):  # Not actually an error. Stack simply hasn't changed
            return None
        wait_for_update = False

    if wait_for_update:
        print('Waiting for stack %s results' % stack_name)
        waiter = client.get_waiter(waiter_name)
        try:
            waiter.wait(StackName=stack_name)
        except WaiterError as e:
            print('Something went wrong')
            print(e)
            return None

        print('Check Stack %s status' % stack_name)
        stack = cf.Stack(stack_name)
        if not stack.stack_status == ok_status:
            print('Failed to create/update stack %s ' % stack_name)
            return None

    outputs = {}
    if stack.outputs:
        for out in stack.outputs:
            key = out['OutputKey']
            val = out['OutputValue']
            print('%s => %s' % (key, val))
            outputs[key] = val

    return outputs


def create_lambda(execution_role):
    # ZIP the lambda folder
    lambda_dir = 'lambda'
    # work_dir = tempfile.mkdtemp()
    work_dir = '/tmp'
    zip_key = 'lambda.zip'
    zip_file_name = work_dir + os.sep + zip_key
    zf = zipfile.ZipFile(zip_file_name, mode='w')
    try:
        # Walk through the lambda folder and add all files to the zip
        for root, directory, files in os.walk(lambda_dir):
            for file in files:
                if file in IGNORED_FILES:
                    continue
                if root in IGNORED_FILES:
                    continue
                file_name = os.path.join(root, file)
                if not file_name.endswith('.pyc') and not file_name.endswith('__init__.py'):
                    arc_name = file_name[len(lambda_dir) + 1:]
                    zf.write(file_name, arcname=arc_name)
                    print(f'Adding {file_name} as {arc_name}')
    finally:
        zf.close()

    # Check if this function already exists
    lambda_client = boto3.client('lambda')
    print('Getting list of existing functions')
    response = lambda_client.list_functions(
        MaxItems=123
    )
    functions = response['Functions']
    existing_function_names = []
    for f in functions:
        existing_function_names.append(f['FunctionName'])

    lambda_name = 'download_hrrr'
    if lambda_name in existing_function_names:
        print(f'Function {lambda_name} already exists, updating it')
        with open(zip_file_name, 'rb') as f:
            lambda_client.update_function_code(
                FunctionName=lambda_name,
                ZipFile=f.read(),
                Publish=True
            )
    else:
        # Create the lambda function
        print(f'Creating lambda function {lambda_name}')
        with open(zip_file_name, 'rb') as f:
            lambda_client.create_function(
                FunctionName=lambda_name,
                Runtime='python3.9',
                Handler=lambda_name + '.handler',
                Code={
                    'ZipFile': f.read()
                },
                Role=execution_role,
                Description='Downloads HRRR data',
                Timeout=300,
                MemorySize=128,
                Publish=True
            )


def deploy(args):
    boto3.setup_default_session(profile_name=args.profile)

    parameters = []
    out = deploy_stack('hrrr-host', parameters)
    execution_role = out['LambdaExecutionRoleArn']

    lambda_arn = create_lambda(execution_role)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
    parser.add_argument("--profile", help="Name of AWS profile to deploy this stack", required=True)

    deploy(parser.parse_args())
