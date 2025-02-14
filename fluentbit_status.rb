Facter.add(:fluentd) do
  setcode do
    service_name = 'fluentd'
    os_family = Facter.value(:os)['family']
    os_release = Facter.value(:os)['release']['major'].to_i

    fluentd_info = {
      'status'  => 'NA',
      'enabled' => 'NA'
    }

    begin
      if os_family == 'RedHat' || os_family == 'Debian'
        if os_release >= 7
          enabled_status = Facter::Core::Execution.execute("systemctl is-enabled #{service_name} 2>/dev/null || echo 'disabled'").strip
          service_status = Facter::Core::Execution.execute("systemctl is-active #{service_name} 2>/dev/null").strip

          fluentd_info['enabled'] = (enabled_status == 'enabled' ? true : false)
          fluentd_info['status'] = (service_status == 'active' ? 'running' : 'stopped')

        elsif os_release == 6
          enabled_status = Facter::Core::Execution.execute("chkconfig --list #{service_name} 2>/dev/null | grep -q 'on' && echo 'enabled' || echo 'disabled'").strip
          service_status = Facter::Core::Execution.execute("service #{service_name} status 2>/dev/null | grep -q 'running' && echo 'running' || echo 'stopped'").strip

          fluentd_info['enabled'] = (enabled_status == 'enabled' ? true : false)
          fluentd_info['status'] = service_status
        end

      elsif os_family == 'Windows'
        service_check = Facter::Core::Execution.execute("sc query #{service_name} 2>&1").strip

        unless service_check.include?("FAILED 1060")
          status_output = Facter::Core::Execution.execute("sc query #{service_name} | findstr STATE").strip
          start_mode = Facter::Core::Execution.execute("sc qc #{service_name} | findstr START_TYPE").strip

          fluentd_info['status'] = status_output.include?("RUNNING") ? 'running' : 'stopped'
          fluentd_info['enabled'] = start_mode.include?("AUTO") ? true : false
        else
          fluentd_info['status'] = 'not installed'
          fluentd_info['enabled'] = false
        end
      end
    rescue => e
      fluentd_info['status'] = "Error: #{e.message}"
      fluentd_info['enabled'] = "Error"
    end

    fluentd_info
  end
end
