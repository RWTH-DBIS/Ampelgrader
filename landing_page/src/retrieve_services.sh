#!/bin/bash

# Retrieve services from Kubernetes and format them as JSON
kubectl get ingress -o json -A | jq '[.items[] | {host: .spec.rules[].host}]' > services.json