python setup.py install --single-version-externally-managed -O1 --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES

#only files but directories are recorded in INSTALLED_FILES
#need to include all sub-directories, otherwise non-empty directory won't be deleted on removal of rpm package
#The following adds "%dir dirname" to the INSTALLED_FILES, so that rpm (spec) knows what directories it owns.
tee -a add_dirs.sh << 'EOF'
#!/bin/bash
exclude_dirs=(
   /usr/bin
   /usr/lib/systemd/system
   /etc/neutron/plugins/ml2
)
array_contains () {
    local seeking=$1; shift
    local in=1
    for element; do
        if [[ $element == $seeking ]]; then
            in=0
            break
        fi
    done
    return $in
}

i=0
while read -r fileline; do
    dir=`dirname $fileline`
    if array_contains $dir "${exclude_dirs[@]}"; then
       #match
       echo "$dir excluded"  
    else
       #no match
       dirs[$i]=$dir
       ((i++))
    fi
done < INSTALLED_FILES

uniq_dirs=($(printf "%s\n" "${dirs[@]}" | sort -u))
##printf "%%dir %s\n" "${uniq_dirs[@]}" >> INSTALLED_FILES
i=0
for item in "${uniq_dirs[@]}"
do
   output[$i]="%dir $item"
   ((i++))
done
printf "%s\n" "${output[@]}" >> INSTALLED_FILES
EOF
chmod +x ./add_dirs.sh
./add_dirs.sh

