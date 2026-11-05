#!/bin/bash
# Get Hohonu dataset ncoJson metadata from SECOORA ERDDAP
# and write to an ncoJson file.
#
# Examples:
# ./get-secoora-dataset.sh fernandina-beach-1-fl io_hohonu_fernandina_beach_1
# ./get-secoora-dataset.sh hohonu_10036_captiva_island_fl io_hohonu_captiva_island

SECOORA_ERDDAP_ID="$1"
BUOY_RETRIEVER_ID="$2"

cd "$(dirname "$0")" || exit
mkdir -p ./metadata

curl -sS "https://erddap.secoora.org/erddap/info/${SECOORA_ERDDAP_ID}.ncoJson" \
  > "./metadata/${BUOY_RETRIEVER_ID}.json"
