from __future__ import annotations

ISSUE_CATEGORIES = {
    "STORAGE",
    "VM_CONFIG",
    "MTV",
    "VMWARE",
    "OCV",
    "NETWORK",
    "CDI",
    "GUEST",
    "AUTOMATION",
    "PORTAL",
    "PLATFORM",
    "ACCESS",
    "UNKNOWN",
}

ISSUE_TAGS = {
    "STORAGE.CSI.PROVISIONING_TIMEOUT": "STORAGE",
    "STORAGE.PVC.PENDING": "STORAGE",
    "STORAGE.PV.ATTACH_FAILURE": "STORAGE",
    "STORAGE.BACKEND.PORTWORX": "STORAGE",
    "STORAGE.BACKEND.DELL": "STORAGE",
    "STORAGE.BACKEND.TRIDENT": "STORAGE",
    "VM_CONFIG.UNSUPPORTED_DEVICE": "VM_CONFIG",
    "VM_CONFIG.DISK_CONFIGURATION": "VM_CONFIG",
    "VM_CONFIG.CPU_MEMORY": "VM_CONFIG",
    "MTV.NETWORK_MAP.INVALID": "MTV",
    "MTV.STORAGE_MAP.INVALID": "MTV",
    "MTV.MIGRATION_CONTROLLER": "MTV",
    "MTV.PLAN_VALIDATION": "MTV",
    "MTV.HOOK_FAILURE": "MTV",
    "MTV.MIGRATION_TIMEOUT": "MTV",
    "VMWARE.CBT": "VMWARE",
    "VMWARE.SNAPSHOT": "VMWARE",
    "VMWARE.VDDK": "VMWARE",
    "VMWARE.VCENTER": "VMWARE",
    "VMWARE.ESXI": "VMWARE",
    "VMWARE.PERMISSION": "VMWARE",
    "VMWARE.DATASTORE": "VMWARE",
    "OCV.VM": "OCV",
    "OCV.VMI": "OCV",
    "OCV.VIRT_LAUNCHER": "OCV",
    "OCV.SCHEDULING": "OCV",
    "OCV.BOOT": "OCV",
    "OCV.KUBEVIRT": "OCV",
    "NETWORK.NAD.MISSING": "NETWORK",
    "NETWORK.OVN": "NETWORK",
    "NETWORK.MULTUS": "NETWORK",
    "NETWORK.DNS": "NETWORK",
    "NETWORK.MTU": "NETWORK",
    "NETWORK.CONNECTIVITY": "NETWORK",
    "CDI.DATAVOLUME": "CDI",
    "CDI.IMPORTER": "CDI",
    "CDI.CONVERSION": "CDI",
    "CDI.DISK_TRANSFER": "CDI",
    "GUEST.WINDOWS": "GUEST",
    "GUEST.VSS": "GUEST",
    "GUEST.BOOT": "GUEST",
    "GUEST.DRIVER": "GUEST",
    "GUEST.APPLICATION": "GUEST",
    "AUTOMATION.ANSIBLE": "AUTOMATION",
    "AUTOMATION.EDA": "AUTOMATION",
    "AUTOMATION.KAFKA": "AUTOMATION",
    "PORTAL.AIRFLOW": "PORTAL",
    "PORTAL.FASTAPI": "PORTAL",
    "PORTAL.DATABASE": "PORTAL",
    "PLATFORM.NODE": "PLATFORM",
    "PLATFORM.KUBELET": "PLATFORM",
    "PLATFORM.CRIO": "PLATFORM",
    "PLATFORM.API": "PLATFORM",
    "PLATFORM.CAPACITY": "PLATFORM",
    "ACCESS.VCENTER_RBAC": "ACCESS",
    "ACCESS.K8S_RBAC": "ACCESS",
    "ACCESS.CREDENTIAL": "ACCESS",
}

# Required evidence policy. Tool names are canonical capabilities, not arbitrary
# functions an LLM is permitted to invent.
INVESTIGATION_POLICIES = {
    "STORAGE.CSI.PROVISIONING_TIMEOUT": {
        "required": [
            "get_migration_context",
            "get_datavolume",
            "get_pvc",
            "get_storageclass",
            "get_volumeattachment",
        ],
        "optional": ["get_csi_logs", "get_storage_backend_status"],
        "knowledge": ["rhokp", "sre_tracker"],
    },
    "VMWARE.CBT": {
        "required": [
            "get_migration_context",
            "get_vcenter_events",
            "get_source_vm_state",
        ],
        "optional": ["get_vmware_task_history", "get_recent_cluster_changes"],
        "knowledge": ["rhokp", "sre_tracker"],
    },
    "NETWORK.NAD.MISSING": {
        "required": ["get_migration_context", "get_networkmap", "get_nad"],
        "optional": ["get_multus_status", "get_ovn_status"],
        "knowledge": ["rhokp", "sre_tracker"],
    },
    "MTV.MIGRATION_TIMEOUT": {
        "required": ["get_migration_context", "get_migration_metrics", "search_splunk_for_migration"],
        "optional": ["get_recent_cluster_changes", "get_cluster_health"],
        "knowledge": ["rhokp", "sre_tracker"],
    },
}

DEFAULT_REQUIRED = ["get_migration_context", "search_splunk_for_migration", "get_cluster_health"]

RECOMMENDATION_POLICIES = {
    "MTV.MIGRATION_TIMEOUT": {
        "action_type": "INVESTIGATE",
        "summary": "Investigate the migration data path and current throughput before selecting fix-forward, retry, or rollback.",
        "steps": [
            "Review MTV migration progress, remaining bytes, throughput trend, and sample count.",
            "Correlate the timeout with MTV/Forklift, CDI, storage, and cluster evidence for the same migration attempt.",
            "Determine whether the data path is progressing, stalled, or blocked by a current resource condition.",
            "Recalculate maintenance-window impact before selecting a recovery option.",
        ],
        "preconditions": [
            "Current migration performance evidence is available and correlated to the failed migration.",
            "Human/SRE review is completed before any retry, rollback, or fix-forward action.",
        ],
        "do_not_do": [
            "Do not infer timeout cause from elapsed time alone.",
            "Do not retry solely because throughput is temporarily low without checking the current failure condition.",
        ],
    },
    "STORAGE.CSI.PROVISIONING_TIMEOUT": {
        "action_type": "FIX_FORWARD",
        "summary": "Investigate and resolve target-side CSI provisioning before retrying the migration.",
        "steps": [
            "Review CSI controller errors around the failure timestamp.",
            "Validate the target StorageClass and PVC provisioning path.",
            "Verify backend volume provisioning and attachment state.",
            "Retry the migration only after the storage condition is resolved.",
        ],
        "preconditions": [
            "Current PVC/CSI evidence confirms the provisioning condition is cleared.",
            "Human/SRE review is completed before retry.",
        ],
    },
    "VMWARE.CBT": {
        "action_type": "FIX_FORWARD",
        "summary": "Investigate VMware CBT/snapshot state before retrying the migration.",
        "steps": [
            "Review vCenter snapshot/CBT events in the migration failure window.",
            "Validate CBT and snapshot state on the source VM.",
            "Resolve the VMware-side condition through the approved operational procedure.",
            "Retry the migration after the source-side condition is verified healthy.",
        ],
        "preconditions": [
            "The VMware condition is confirmed as resolved.",
            "Human/SRE review is completed before retry.",
        ],
    },
    "NETWORK.NAD.MISSING": {
        "action_type": "FIX_FORWARD",
        "summary": "Correct the target network mapping/NAD relationship before retrying the migration.",
        "steps": [
            "Verify the NetworkMap source-to-target mapping.",
            "Verify the referenced NetworkAttachmentDefinition exists and is usable.",
            "Validate Multus/OVN health when the mapping and NAD are correct but attachment still fails.",
            "Retry the migration after network validation succeeds.",
        ],
        "preconditions": [
            "NetworkMap/NAD evidence shows the target network is valid.",
            "Human/SRE review is completed before retry.",
        ],
    },
}

# Recovery paths are deliberately declarative. They describe approved option
# templates; they do not authorize execution. Runtime action catalogs/AAP/EDA
# remain the enforcement point after human approval.
RECOVERY_POLICIES = {
    "STORAGE.CSI.PROVISIONING_TIMEOUT": {
        "options": [
            {
                "type": "FIX_FORWARD", "risk": "MEDIUM",
                "summary": "Restore target storage provisioning health, validate the PVC path, then retry.",
                "preconditions": ["Storage owner confirms backend condition can be safely corrected.", "PVC/CSI state is observable after the change."],
                "changes": ["Resolve the approved CSI/backend condition or workaround.", "Revalidate StorageClass, PVC and VolumeAttachment."],
                "validation": ["PVC is Bound/usable.", "No active CSI provisioning errors.", "Storage backend is healthy.", "Migration artifacts are clean."],
                "rollback": ["Stop the retry and restore the storage state using the approved storage runbook if the change worsens the condition."],
            },
            {
                "type": "ROLLBACK", "risk": "LOW",
                "summary": "Rollback/abandon the migration attempt when target storage cannot be made healthy within the window.",
                "preconditions": ["Rollback procedure is approved for the migration phase.", "Application/source VM remains available."],
                "changes": [],
                "validation": ["Source VM/application remains healthy.", "Target migration artifacts are left in the documented rollback state."],
                "rollback": [],
            },
            {
                "type": "RETRY", "risk": "MEDIUM",
                "summary": "Retry only after deterministic storage readiness checks pass.",
                "preconditions": ["All retry-readiness checks PASS."],
                "changes": [],
                "validation": ["Migration starts without recreating the same storage failure."],
                "rollback": ["Use the migration rollback procedure if the retry fails again."],
            },
        ]
    },
    "VMWARE.CBT": {
        "options": [
            {
                "type": "FIX_FORWARD", "risk": "MEDIUM",
                "summary": "Correct the VMware CBT/snapshot condition using an approved VM-level or vCenter procedure, then retry.",
                "preconditions": ["No active backup/snapshot operation conflicts with the change.", "Application/VM owner approves any VM-level configuration change."],
                "changes": ["Apply the approved CBT/snapshot remediation.", "If a known workaround applies, temporarily change only the documented VM-level setting/device."],
                "validation": ["CBT/snapshot state is healthy.", "Source VM remains healthy.", "No conflicting backup operation is active."],
                "rollback": ["Restore the original VM-level configuration from the captured pre-change state if the workaround is not required."],
            },
            {
                "type": "RETRY", "risk": "MEDIUM",
                "summary": "Retry the migration after CBT/snapshot readiness is verified.",
                "preconditions": ["CBT_HEALTHY and VCENTER_HEALTHY checks PASS."],
                "changes": [],
                "validation": ["Warm-import/pre-stage progresses beyond the prior failure point."],
                "rollback": ["Use the migration rollback procedure if the retry fails again."],
            },
            {
                "type": "ROLLBACK", "risk": "LOW",
                "summary": "Stop the migration attempt when the VMware condition cannot be safely corrected within the window.",
                "preconditions": ["Source VM/application is confirmed healthy."],
                "changes": [],
                "validation": ["Source workload remains available and migration artifacts are cleaned up as required."],
                "rollback": [],
            },
        ]
    },
    "NETWORK.NAD.MISSING": {
        "options": [
            {
                "type": "FIX_FORWARD", "risk": "MEDIUM",
                "summary": "Correct the NetworkMap/NAD configuration, validate attachment, then retry.",
                "preconditions": ["Network owner confirms the target NAD is intended and approved.", "The requested NAD change is within the migration change scope."],
                "changes": ["Create/correct the target NAD or NetworkMap using the approved configuration."],
                "validation": ["NetworkMap is valid.", "NAD exists and is usable.", "Multus/OVN attachment path is healthy."],
                "rollback": ["Restore the prior NetworkMap/NAD configuration if the change causes attachment problems."],
            },
            {
                "type": "RETRY", "risk": "MEDIUM",
                "summary": "Retry after network readiness checks pass.",
                "preconditions": ["NETWORKMAP_VALID, NAD_VALID and NETWORK_HEALTHY checks PASS."],
                "changes": [],
                "validation": ["Target interface attaches successfully."],
                "rollback": ["Use migration rollback if the retry fails again."],
            },
            {
                "type": "ROLLBACK", "risk": "LOW",
                "summary": "Rollback/stop the migration if the target network cannot be made valid within the window.",
                "preconditions": ["Source VM/application remains healthy."],
                "changes": [],
                "validation": ["Source workload remains available."],
                "rollback": [],
            },
        ]
    },
    "VM_CONFIG.UNSUPPORTED_DEVICE": {
        "options": [
            {
                "type": "FIX_FORWARD", "risk": "MEDIUM",
                "summary": "Temporarily remove or reconfigure the documented unsupported VM device, validate the guest, then retry migration.",
                "preconditions": ["Device is confirmed unused or application owner approves its temporary removal.", "Original VM configuration is captured for rollback."],
                "changes": ["Apply only the approved VM-level device workaround from the runbook/SRE Tracker."],
                "validation": ["VM powers on and guest/application health checks pass.", "Migration validation no longer reports the unsupported device."],
                "rollback": ["Restore the captured VM device configuration if migration is abandoned or the workaround is no longer needed."],
            },
            {
                "type": "ROLLBACK", "risk": "LOW",
                "summary": "Do not alter the VM when the device dependency is unclear; defer migration and preserve the source state.",
                "preconditions": ["Dependency on the device cannot be safely ruled out."],
                "changes": [],
                "validation": ["Source VM remains unchanged and healthy."],
                "rollback": [],
            },
        ]
    },
}

OWNER_BY_CATEGORY = {
    "STORAGE": "storage",
    "VMWARE": "vmware_admins",
    "NETWORK": "network",
    "OCV": "sre_day2",
    "MTV": "sre_day2",
    "CDI": "sre_day2",
    "VM_CONFIG": "vmware_admins",
    "PLATFORM": "sre_day2",
    "ACCESS": "sre_day2",
    "GUEST": "build",
    "AUTOMATION": "build",
    "PORTAL": "build",
    "UNKNOWN": "sre_day2",
}

# Deterministic operational checks used after diagnosis. These are intentionally
# separate from recommendation prose: the LLM cannot weaken these gates.
RETRY_CHECKS = {
    "STORAGE.CSI.PROVISIONING_TIMEOUT": [
        ("PVC_HEALTHY", "PVC is Bound/usable", ["PVC_BOUND"], ["PVC_PENDING"]),
        ("CSI_ERRORS_CLEARED", "No active CSI provisioning errors", ["CSI_ERRORS_CLEARED"], ["CSI_PROVISIONING_TIMEOUT"]),
        ("BACKEND_HEALTHY", "Storage backend is healthy", ["STORAGE_BACKEND_HEALTHY"], ["STORAGE_BACKEND_DEGRADED", "BACKEND_PROVISIONING_FAILURE"]),
        ("MIGRATION_CLEANUP_COMPLETE", "Previous migration artifacts are clean", ["MIGRATION_CLEANUP_COMPLETE"], ["MIGRATION_CLEANUP_PENDING"]),
    ],
    "VMWARE.CBT": [
        ("CBT_HEALTHY", "VMware CBT/snapshot state is healthy", ["CBT_HEALTHY"], ["CBT_SNAPSHOT_FAILURE", "WARM_IMPORT_RETRY_EXHAUSTED"]),
        ("VCENTER_HEALTHY", "vCenter control-plane connectivity is healthy", ["VCENTER_HEALTHY"], ["VCENTER_CONNECTIVITY_FAILURE"]),
    ],
    "NETWORK.NAD.MISSING": [
        ("NETWORKMAP_VALID", "NetworkMap target mapping is valid", ["NETWORKMAP_VALID"], ["NETWORKMAP_INVALID"]),
        ("NAD_VALID", "Target NAD exists and is usable", ["NAD_VALID"], ["NAD_MISSING"]),
        ("NETWORK_HEALTHY", "Multus/OVN attachment path is healthy", ["NETWORK_HEALTHY"], ["NETWORK_ATTACHMENT_FAILURE"]),
    ],
}
