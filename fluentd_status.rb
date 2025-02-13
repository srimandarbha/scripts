Facter.add(:fluentd_status) do
  setcode do
    service_name = 'fluentd'
    os_family = Facter.value(:os)['family']
    os_release = Facter.value(:os)['release']['major'].to_i
    status = 'NA'

    if os_family == 'RedHat' || os_family == 'Debian'
      if os_release >= 7
        service_check = Facter::Core::Execution.execute("systemctl list-unit-files | grep -Fq #{service_name}.service && echo 'yes' || echo 'no'").strip
        if service_check == 'yes'
          status = Facter::Core::Execution.execute("systemctl is-active #{service_name} 2>/dev/null").strip
          status = (status == 'active' ? 'running' : 'stopped')
        end
      elsif os_release == 6
        service_check = Facter::Core::Execution.execute("chkconfig --list | grep -Fq #{service_name} && echo 'yes' || echo 'no'").strip
        if service_check == 'yes'
          status = Facter::Core::Execution.execute("service #{service_name} status 2>/dev/null | grep -q 'running' && echo 'running' || echo 'stopped'").strip
        end
      end
    elsif os_family == 'Windows'
      service_check = Facter::Core::Execution.execute("sc query #{service_name} 2>&1").strip
      if !service_check.include?("FAILED 1060")
        status = Facter::Core::Execution.execute("sc query #{service_name} | findstr STATE").strip
        status = status.include?("RUNNING") ? 'running' : 'stopped'
      end
    end

    status
  end
end
