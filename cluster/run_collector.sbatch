#!/bin/bash
#SBATCH --job-name=delivery-collector
#SBATCH --partition=<PARTITION>
#SBATCH --time=00:10:00
#SBATCH --mem=512M
#SBATCH --cpus-per-task=1
#SBATCH --output=logs/collector-%j.out
#SBATCH --error=logs/collector-%j.err
#SBATCH --mail-type=FAIL
#SBATCH --mail-user=you@example.com

# Em jobs do Slurm, o script é copiado para /var/spool/slurmd. 
# SLURM_SUBMIT_DIR aponta para o diretório de onde o job foi submetido (a raiz do projeto).
PROJECT_DIR="$SLURM_SUBMIT_DIR"

# Ensure log directory exists
mkdir -p "$PROJECT_DIR/logs"

# Execute the collection within the Apptainer container
# We bind-mount necessary folders so data is saved directly on the host filesystem.
# The container image collector.sif must be built first: apptainer build collector.sif cluster/collector.def
apptainer exec \
    --bind "$PROJECT_DIR/data:/app/data" \
    --bind "$PROJECT_DIR/config:/app/config" \
    --bind "$PROJECT_DIR/logs:/app/logs" \
    --bind "$PROJECT_DIR/src:/app/src" \
    --bind "$PROJECT_DIR/run_collector.py:/app/run_collector.py" \
    --bind "$PROJECT_DIR/API_KEYS.txt:/app/API_KEYS.txt:ro" \
    "$PROJECT_DIR/collector.sif" python /app/run_collector.py --action matrix
