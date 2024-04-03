import argparse
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
                Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM'],
                Parameters=parameters,
                UsePreviousTemplate=False
            )
            waiter_name = 'stack_update_complete'
            ok_status = 'UPDATE_COMPLETE'
        else:
            client.create_stack(
                StackName=stack_name,
                TemplateBody=open(template_file, 'r').read(),
                Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM'],
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


def deploy(args):
    boto3.setup_default_session(profile_name=args.profile)

    parameters = [
        {'ParameterKey': 'SubnetId1', 'ParameterValue': args.subnet},
    ]
    deploy_stack('hrrr-host', parameters)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
    parser.add_argument("--profile", help="Name of AWS profile to deploy this stack", required=True)
    parser.add_argument("--subnet", help="Name of subnet to use", required=True)

    deploy(parser.parse_args())
