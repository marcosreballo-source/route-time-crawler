#!/bin/bash

# Find absolute path of the directory containing this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SBATCH_PATH="$SCRIPT_DIR/run_collector.sbatch"
LOGS_DIR="$( cd "$SCRIPT_DIR/.." && pwd )/logs"

# Verify file exists
if [ ! -f "$SBATCH_PATH" ]; then
    echo "Error: run_collector.sbatch not found at $SBATCH_PATH"
    exit 1
fi

echo "Installing Fase 3 scrontab scheduling (Longo Prazo)..."
echo "Using batch script: $SBATCH_PATH"
echo "Writing logs to: $LOGS_DIR"

# Generate and load crontab
cat << EOF | crontab -
# Fase 3: Controle de Longo Prazo para retail matrix collection
# Frequencia: 4 snapshots por dia (07:30, 12:30, 18:00, 23:00)

# Executar aos 30 min (07:30, 12:30, 18:30) e exato (23:00)
30 7,12,18 * * * cd $SCRIPT_DIR/.. && sbatch $SBATCH_PATH
0 23 * * * cd $SCRIPT_DIR/.. && sbatch $SBATCH_PATH
EOF

echo "crontab updated successfully para a Fase 3. List configured schedules with: crontab -l"
