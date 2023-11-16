import os
import time
import argparse
import pytfc
import gitlab
import json

TFE_HOSTNAME = os.getenv('TFE_HOSTNAME', 'app.terraform.io')
TFE_TOKEN = os.getenv('TFE_TOKEN')
TFE_ORG = os.getenv('TFE_ORG')

GL_URL = os.getenv('GL_URL', 'https://gitlab.com')
GL_TOKEN = os.getenv('GL_TOKEN')
GL_PROJECT_ID = os.getenv('GL_PROJECT_ID')


def tfc_api_wf(tfc_client, ws_id, tf_dir):
    """
    Function to execute TFC/E API-driven run workflow.
    """
    cv_id = tfc_client.configuration_versions.create_and_upload(
        ws_id=ws_id,
        source_tf_dir=tf_dir,
        auto_queue_runs=False,
        cleanup=True
    )

    run = tfc_client.runs.create(
        ws_id=ws_id,
        cv_id=cv_id,
        auto_apply=True
    )
    
    run_id = run.json()['data']['id']
    return run_id

def py_dict_to_hcl_map(py_dict):
    """
    Utility function to convert a Python
    dictionary to an HCL map.
    """
    max_key_length = max(len(k) for k in py_dict.keys())
    hcl_map = ["{"]
    
    for k, v in py_dict.items():
        kv_spacing = max_key_length - len(k) + 1
        if isinstance(v, str):
            fmt_val = f'"{v}"' if not v.startswith('"') else v
        else:
            fmt_val = v
        hcl_map.append(f'  {k}{" " * kv_spacing}= {fmt_val}')
    hcl_map.append("}")

    return "\n".join(hcl_map)

def inject_tfvars(template_path, vars):
    """
    Utility function to inject the input variable values
    into the terraform.tfvars.tpl template file.
    """
    tfvars_rendered = []
    max_key_length = max(len(key) for key in vars.keys())

    with open(template_path, 'r') as input_file:
        for line in input_file:
            parts = line.split('=')
            if len(parts) == 2:
                key = parts[0].strip()
                value = vars.get(key, None)
                
                if value is not None:
                    if isinstance(value, str):
                        fmt_line = f'{key.ljust(max_key_length)} = "{value}"\n'
                        tfvars_rendered.append(fmt_line)
                    elif isinstance(value, int):
                        fmt_line = f'{key.ljust(max_key_length)} = {value}\n'
                        tfvars_rendered.append(fmt_line)
                    elif isinstance(value, list):
                        value_str = f"{value}"
                        fmt_line = f'{key.ljust(max_key_length)} = {value_str}\n'
                        tfvars_rendered.append(fmt_line)
                    elif isinstance(value, dict):
                        hcl_map = py_dict_to_hcl_map(value)
                        fmt_line = f'{key.ljust(max_key_length)} = {hcl_map}\n'
                        tfvars_rendered.append(fmt_line)
                    else:
                        print(f"Unexpected format: {type(value)}:")
                        print(value)
                        print("Skipping this variable.")
    
    return ''.join(tfvars_rendered)

def gl_commit_payload(dst_path, content):
    """
    Utility function to create payload for a commit.
    """
    changes = {
        'action': 'create',
        'file_path': dst_path,
        'content': content
    }
    return changes

def gitlab_config(gl_client, gl_project_id, templates_dir, dst_dir, input_vars):
    """
    Function to create new folder and files in existing GitLab project.
    """
    gl_project = gl_client.projects.get(gl_project_id)
    os.makedirs(dst_dir, exist_ok=True)
    changes_list = []
    for tf_file in os.listdir(templates_dir):
        if tf_file.endswith('.tf'):
            src_path = os.path.join(templates_dir, tf_file)
            dst_path = os.path.join(dst_dir, tf_file)
            content = open(src_path, 'r').read()
            
            print(f"[gl] Staging commit for '{dst_path}' in repo...")
            tf_changes = gl_commit_payload(dst_path, content)
            changes_list.append(tf_changes)

            print(f"[gl] Creating '{dst_path}' locally...")
            with open(src_path, 'rb') as src_file, open(dst_path, 'wb') as dst_file:
                dst_file.write(src_file.read())

    if input_vars is not None:
        src_tfvars_path = f'{templates_dir}/template.tfvars.tpl'
        dst_tfvars_path = f'{dst_dir}/terraform.auto.tfvars'
        if not os.path.isfile(src_tfvars_path):
            print(f"[Error] Path '{src_tfvars_path}' not found.")
            exit(f"Ensure that '{src_tfvars_path}' exists within the repo.")
        else:
            print("[gl] Rendering variable values for new TFVARS file...")
            tfvars_rendered = inject_tfvars(src_tfvars_path, input_vars)
            
            print(f"[gl] Staging commit for '{dst_tfvars_path}'...")
            tfvars_changes = gl_commit_payload(dst_tfvars_path, tfvars_rendered)
            changes_list.append(tfvars_changes)

            print(f"[gl] Creating '{dst_tfvars_path}' in locally...")
            with open(dst_tfvars_path, 'w') as tfvars_file:
                tfvars_file.write(tfvars_rendered)
    else:
        print("[gl] No input vars were specified. Skipping TFVARS template rendering.")
        tfvars_rendered = None

    print("[gl] Pushing new commit to repo...")
    script_name = os.path.basename(__file__)
    gl_project.commits.create({
        'branch': 'main',
        'actions': changes_list,
        'commit_message': f'Created by {script_name}'
    })

def tfc_ws_create(tfc_client, name, project_name, vcs_repo, oauth_token_id, dst_dir, varset_name, outputs):
    """
    Function to create new TFC Workspace, trigger a Terraform
    plan and apply, and return any outputs specified.
    """
    is_vcs_workflow = True if vcs_repo is not None else False
    project_id = (
        tfc_client.projects.get_project_id(name=project_name)
        if project_name is not None
        else None
    )
    working_dir = dst_dir if is_vcs_workflow else None
    trigger_patterns = [f'{dst_dir}/*.tf'] if is_vcs_workflow else None
    oauth_token_id = oauth_token_id if is_vcs_workflow else None

    print(f"[tfc] Creating workspace '{name}'...")
    ws = tfc_client.workspaces.create(
        name=name,
        project_id=project_id,
        identifier=vcs_repo,
        oauth_token_id=oauth_token_id,
        working_directory=working_dir,
        trigger_patterns=trigger_patterns,
        queue_all_runs=False
    )
    ws_id = ws.json()['data']['id']

    if varset_name is not None:
        print(f"[tfc] Fetching variable set ID for {varset_name}...")
        varset_id = tfc_client.variable_sets.get_varset_id(name=varset_name)
        print("[tfc] Applying variable set to workspace...")
        tfc_client.variable_sets.apply_to_workspace(varset_id=varset_id, ws_id=ws_id)

    script_name = os.path.basename(__file__)
    if is_vcs_workflow:
        cv_id = tfc_client.configuration_versions._get_latest_cv_id(ws_id=ws_id)
        while True:
            cv_status = tfc_client.configuration_versions.get_cv_status(cv_id)
            if cv_status == 'uploaded':
                break
            else:
                time.sleep(2)
                print(f"[tfc] Waiting for code to upload... {cv_status}")
        time.sleep(1)
        print("[tfc] Running VCS-driven workflow.")
        run = tfc_client.runs.create(ws_id=ws_id, auto_apply=True, message=f'Triggered by {script_name}')
        run_id = run.json()['data']['id']
    else:
        print("[tfc] Running API-driven workflow.")
        run_id = tfc_api_wf(tfc_client, ws_id, tf_dir=dst_dir)
    
    while True:
        plan_status = tfc_client.runs.show(run_id=run_id).json()['data']['attributes']['status']
        if (plan_status == 'planned' or 
            plan_status == 'planned_and_finished' or 
            plan_status == 'policy_checked' or
            plan_status == 'apply_queued' or 
            plan_status == 'applying' or
            plan_status == 'applied'):
            break
        elif plan_status == 'errored':
            print(f"[tfc] Plan errored. Exiting.")
            exit()
        print(f"[tfc] Waiting for plan to finish... {plan_status}")
        # TODO: add timeout value and logic
        time.sleep(5)

    while True:
        apply_status = tfc_client.runs.show(run_id=run_id).json()['data']['attributes']['status']
        if apply_status == 'applied' or apply_status == 'planned_and_finished':
            break
        elif apply_status == 'errored':
            print(f"[tfc] Apply errored. Exiting.")
            exit()
        print(f"[tfc] Waiting for apply to finish... {apply_status}")
        # TODO: add timeout value and logic
        time.sleep(5)
    
    if outputs is not None:
        outputs_list = [item.strip(',') for item in outputs]
        while True:
            try:
                current_state = tfc_client.state_versions.get_current(ws_id=ws_id).json()
                if current_state['data']['attributes']['resources-processed'] == True:
                    break
                print("[tfc] Waiting for outputs to be processed...")
            except Exception as e:
                if str(e).startswith('404 tfc_client Error: Not Found for url:'):
                    time.sleep(2)
                else:
                    print(f"[tfc] An unexpected exception occurred: {e}")
                    exit("[tfc] Exiting script.")

        sv_id = current_state['data']['id']
        sv_outputs = tfc_client.state_version_outputs.list(sv_id=sv_id).json()
        outputs_data = {}
        for i in sv_outputs['data']:
            if i['attributes']['name'] in outputs_list:
                outputs_data[i['attributes']['name']] = i['attributes']['value']

        if outputs_data:
            print("[tfc] Printing outputs:")
            print(outputs_data)
        
        return outputs_data

def parse_args():
    parser = argparse.ArgumentParser(
        description='TFC Workspace creation and GitLab file creation arguments.')
    parser.add_argument('--name', dest='name',
        help='Name of Workspace to create in TFC.'),
    parser.add_argument('--destination-dir', dest='destination_dir', default=None,
        help='Path of new directory to create where TF files should land.'),
    parser.add_argument('--project-name', dest='project_name', default=None,
        help='Name of TFC Project to place Workspace in.'),
    parser.add_argument('--vcs-repo', dest='vcs_repo', default=None,
        help='Reference to VCS repository in format of :org/:repo.'),
    parser.add_argument('--oauth-token-id', dest='oauth_token_id', default=None,
        help='OAuth Token ID of VCS provider connection in TFC.'),
    parser.add_argument('--working-dir', dest='working_dir', default=None,
        help='Directory in repo that TFC Workspace should be linked to.'),
    parser.add_argument('--varset-name', dest='varset_name', default=None,
        help='Name of TFC Variable Set to apply to Workspace.'),
    parser.add_argument('--templates-dir', dest='templates_dir', default='./templates',
        help='Path to directory where Terraform templates reside.')
    parser.add_argument('--var', nargs='+', action='append', metavar=('key', 'value'),
        default=None, help='User-defined Terraform input variable values.'),
    parser.add_argument('--outputs', nargs='+', dest='outputs', default=None,
        help='List of Terraform outputs to return after the apply.')
    args = parser.parse_args()
    
    return args

def main():
    args = parse_args()

    templates_dir = args.templates_dir
    if not os.path.exists(templates_dir):
        print(f"Error: Path not found for '{templates_dir}'.")
        exit("Please specify a valid path for --templates-dir.")
    else:
        print(f"[gl] Setting templates_dir to '{templates_dir}'.")
        # TODO:
        # Ensure *.tf files and template.tfvars.tpl are present

    if not args.destination_dir:
        print(f"[gl] A destination directory was not specified.")
        print(f"[gl] Setting {args.name} as destination directory.")
        dst_dir = args.name
    else:
        dst_dir = args.destination_dir

    input_vars = {}
    if args.var is not None:
        for var in args.var:
            key, value = var
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
            input_vars[key] = value
    else:
        input_vars = None

    tfc_client = pytfc.Client(hostname=TFE_HOSTNAME, token=TFE_TOKEN, org=TFE_ORG)
    gl_client = gitlab.Gitlab(url=GL_URL, private_token=GL_TOKEN)
    
    # TODO: Validate args.name (Workspace name) is available

    gitlab_config(
        gl_client=gl_client,
        gl_project_id=GL_PROJECT_ID,
        templates_dir=templates_dir,
        dst_dir=dst_dir,
        input_vars=input_vars
    )

    tfc_ws_create(
        tfc_client=tfc_client,
        name=args.name,
        project_name=args.project_name,
        vcs_repo=args.vcs_repo,
        oauth_token_id=args.oauth_token_id,
        dst_dir=dst_dir,
        varset_name=args.varset_name,
        outputs=args.outputs
    )

if __name__ == "__main__":
    main()