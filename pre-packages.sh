#!/bin/bash
# Use an `if` to prevent re-running unnecessarily (though it's idempotent)
if [ ! -f /etc/apt/apt.conf.d/99-expire ]; then
  echo "Aplicando parche para repositorios de seguridad Debian Bullseye caducados..."
  echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99-expire
else
  echo "El parche ya está aplicado."
fi
