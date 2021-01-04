import os,sys,shutil,subprocess
import argparse
import warnings
import yaml
import slurmr
from prompt_toolkit import print_formatted_text as pprint, HTML

    
def main(args):

    # Load config file
    with open(args.config_yaml, 'r') as stream:
        config = yaml.safe_load(stream)
            
    # Check if we have SLURM
    have_slurm = slurmr.check_slurm()
    if not(have_slurm):
        print("No SLURM detected. We will be locally "
              "executing commands serially.")
    if args.dry_run:
        print("We are doing a dry run, so we will just print to "
              "screen.")

    # Do git checks
    slurmr.gitcheck(config,'gitcheck_pkgs',package=True)
    slurmr.gitcheck(config,'gitcheck_paths',package=False)

    # Get global values if any
    global_vals = config.get('globals',{})

    # Get stages in order of dependencies
    cstages = config['stages']
    stage_names = list(cstages.keys())
    deps = {}
    for sname in stage_names:
        ds = cstages[sname].get('depends')
        if ds is not None: 
            deps[sname] = ds
            for d in ds:
                if d not in stage_names: 
                    pprint(HTML(f"<red>Stage {d} required by {sname} not found in configuration file.</red>"))
                    raise Exception

    if slurmr.has_loop(deps): raise Exception("Circular dependency detected.")
    stages = slurmr.flatten(deps) # Ordered by dependency
    # The above only contains stages that depend on something or something also depends on
    # Let's just append any others and warn about them
    for ostage in stage_names:
        if ostage not in stages:
            pprint(HTML(f"<ansiyellow>WARNING: stage {ostage} does not depend on anything, and nothing depends on it. Adding to queue anyway...</ansiyellow>"))
            stages.append(ostage)
    if set(stages)!=set(stage_names): raise Exception("Internal error in arranging stages. Please report this bug.")

    # Make project directory
    proj_dir = os.path.join(config['root_dir'],args.project)
    os.makedirs(proj_dir, exist_ok=True)


    # Parse arguments and prepare SLURM scripts
    cstages = config['stages']

    if have_slurm or args.force_slurm:
        site = slurmr.detect_site() if args.site is None else args.site
        sbatch_config = slurmr.load_template(site)

    jobids = {}
    for stage in stages:
        # Get command
        execution,script,pargs = slurmr.get_command(global_vals, cstages, stage)

        # Make output directory
        output_dir =  os.path.abspath(os.path.join(proj_dir,stage))
        os.makedirs(output_dir, exist_ok=True)

        # Append output directory to arguments
        pargs = pargs + f' --output-dir {output_dir}'

        # Construct dependency string
        now_deps = deps.get(stage,[])
        if len(now_deps)>=1:
            depstr = ':'.join([jobids[s] for s in now_deps])
            depstr = "--dependency=afterok:" + depstr
        else:
            depstr = None
        
        if have_slurm or args.force_slurm:
            jobid = slurmr.submit_slurm(stage,sbatch_config,
                                         cstages[stage].get('parallel',None),
                                         execution,script,pargs,
                                         dry_run=args.dry_run,
                                         output_dir=output_dir,
                                         project=args.project,
                                         site=site,depstr=depstr)
        if not(have_slurm) or args.force_local:
            jobid = slurmr.run_local([execution,script,pargs],dry_run=args.dry_run)

        jobids[stage] = jobid
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description = 'A pipeline script plumbing tool.')
    parser.add_argument('project', help='Name of project.')
    parser.add_argument('config_yaml', help='Path to the configuration file.')
    parser.add_argument("--site",     type=str,  default=None,help="Name of a pre-defined cluster site. "
                        "If not specified, will attempt to detect automatically.")
    parser.add_argument("--dry-run", action='store_true',help='Only show submissions.')
    parser.add_argument("--force-local", action='store_true',help='Force local run.')
    parser.add_argument("--force-slurm", action='store_true',help="Force SLURM. "
                        "If SLURM is not detected and --dry-run is not enabled, this will fail.")
    args = parser.parse_args()
    if args.force_local and args.force_slurm: raise Exception("You can\'t force both local and SLURM.")
    main(args)
