@{
    DomainDnsName = "web-flip.local"
    DomainNetBios  = "WEB-FLIP"
    GroupsOu       = "OU=Groups,OU=HCC,DC=web-flip,DC=local"
    ServiceAccountsOu = "OU=Service Accounts,OU=HCC,DC=web-flip,DC=local"

    # Write all AD objects on one DC; replication distributes them domain-wide.
    WriteDomainController = "HINESDC1"
    DomainControllers = @("HINESDC1", "HINESDC2", "HINESDC3")

    TierGroups = @(
        @{
            Name        = "HCC-Agent-Observers"
            Description = "HCC dashboard read-only. Core RBAC: view fleet and metrics."
            Scope       = "Human"
            CapabilityTier = "observer"
        }
        @{
            Name        = "HCC-Agent-Operators"
            Description = "HCC day-to-day operations. Core RBAC: service/vm start stop restart."
            Scope       = "Human"
            CapabilityTier = "operator"
        }
        @{
            Name        = "HCC-Agent-Maintainers"
            Description = "HCC agent lifecycle. Core RBAC: agent self-update and agent restart."
            Scope       = "Human"
            CapabilityTier = "maintainer"
        }
        @{
            Name        = "HCC-Agent-Deployers"
            Description = "HCC software rollout. Core RBAC: approved software.install actions."
            Scope       = "Human"
            CapabilityTier = "deployer"
        }
        @{
            Name        = "HCC-Agent-ServiceAccounts"
            Description = "HCC agent service principals. Add gMSA svc-hcc-agent here after creation. Host-local execution rights."
            Scope       = "ServicePrincipal"
            CapabilityTier = "operator"
        }
    )

    # Services the agent service account group may start/stop on domain controllers
    DcServices = @(
        "NTDS", "DNS", "DHCP", "KDC", "Netlogon", "W32Time", "WinRM", "W3SVC", "Spooler"
    )

    # Services on member servers / generic Windows servers
    MemberServerServices = @(
        "WinRM", "W3SVC", "Spooler"
    )

    # Workstations: metrics-focused; no service-control ACLs are applied for this role
    ClientServices = @()
}
