import oci
import time
import datetime

# ╔══════════════════════════════════════════════════════╗
# ║  Target : 可选 ARM / x86 免费实例                     ║
# ║  ARM    : VM.Standard.A1.Flex  (aarch64 镜像)         ║
# ║  x86    : VM.Standard.E2.1.Micro (x86_64 镜像)        ║
# ║  Tier   : Oracle Always Free                          ║
# ╚══════════════════════════════════════════════════════╝

# ═══════════════════════════════════════════════════════
#  ★ 用户配置区 ★  —— 只改这里就能切换 ARM / x86
# ═══════════════════════════════════════════════════════

# 抢哪种实例：
#   "arm" → VM.Standard.A1.Flex（ARM，aarch64 镜像）
#   "x86" → VM.Standard.E2.1.Micro（x86_64 镜像）
TARGET_ARCH = "arm"

# —— 以下仅 ARM 模式生效 ——
# ARM 免费额度是【账户级总共】2 OCPU / 12 GB，可自由拆分给多个实例。
#   想要一个满配 ARM 实例：ARM_OCPUS = 2, ARM_MEMORY_IN_GBS = 12
#   想要两个小 ARM 实例：  ARM_OCPUS = 1, ARM_MEMORY_IN_GBS = 6（各一台）
ARM_OCPUS = 1
ARM_MEMORY_IN_GBS = 6

# ARM 镜像偏好：
#   True  → 优先 Minimal 版（Oracle 上 ARM 的 Ubuntu 通常只有 Minimal）
#   False → 优先完整版（若该区域提供）
ARM_PREFER_MINIMAL = True

# 实例名称（会自动根据 TARGET_ARCH 选用默认名，也可手动改）
INSTANCE_NAME = "arm-server" if TARGET_ARCH == "arm" else "micro-server"

# 引导卷大小（GB）
BOOT_VOLUME_SIZE_IN_GBS = 50

# 重试间隔（秒）
RETRY_INTERVAL = 30

# ═══════════════════════════════════════════════════════
#  固定配置（一般不用改）
# ═══════════════════════════════════════════════════════
COMPARTMENT_ID = (
    "ocid1.tenancy.oc1..aaaaaaaaaqij5zlnm3v5qprvdll3j7nc6o3dk4ykzerugzxe37ckajkpjxpa"
)
SSH_PUBLIC_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCxPqVeut2vbwt8VVAvHDnEN+q61jrIAGD9cQgW6kTeLCjjzm9UHt2Flf1KoohSu+0YFvSn8+t67r9T9wfdP14WBfZAg531CCyUNTbF5KmkaHgmxftWu3FgY00BTnGa4YEEXdAGn3X953HzFKJDpJVJyWFfWXJUOWdfivTKlO+62SBnlIdcanckwA6rzr9dXNSYlasoVnuk+ujANjhnxf4TpKcI4AQrAmRJQ83lXfI2yExBMX+Qx/JNSA2/2XFRfT7OMgddExibCRpSyammfatNLUIM5s+ab6aeO3aNvVWGok6/dpYaBPbvndERQs6p9FQr88C/VFeEwHCtvMT8c2WB ssh-key-2026-03-07"
# ═══════════════════════════════════════════════════════

config = oci.config.from_file()

# —— 根据 TARGET_ARCH 派生配置 ——
if TARGET_ARCH == "arm":
    SHAPE = "VM.Standard.A1.Flex"
    HAS_SHAPE_CONFIG = True
    VCN_NAME = "retry-vcn-arm"
    SUBNET_NAME = "retry-subnet-arm"
    VCN_CIDR = "10.2.0.0/16"
    SUBNET_CIDR = "10.2.0.0/24"
elif TARGET_ARCH == "x86":
    SHAPE = "VM.Standard.E2.1.Micro"
    HAS_SHAPE_CONFIG = False
    VCN_NAME = "retry-vcn-micro"
    SUBNET_NAME = "retry-subnet-micro"
    VCN_CIDR = "10.1.0.0/16"
    SUBNET_CIDR = "10.1.0.0/24"
else:
    raise ValueError('TARGET_ARCH 只能是 "arm" 或 "x86"')


def get_availability_domains():
    """ARM: 返回所有 AD；x86: 只返回第一个 AD（AMD Micro 免费实例通常只能在指定 AD 创建）"""
    identity = oci.identity.IdentityClient(config)
    ads = identity.list_availability_domains(COMPARTMENT_ID).data
    names = [ad.name for ad in ads]
    if TARGET_ARCH == "arm":
        return names
    return names[:1]


def get_image():
    """根据 TARGET_ARCH 自动选择正确的镜像"""
    compute = oci.core.ComputeClient(config)
    images = compute.list_images(
        COMPARTMENT_ID,
        operating_system="Canonical Ubuntu",
        shape=SHAPE,
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data

    if TARGET_ARCH == "arm":
        # —— ARM：必须有 aarch64，按 ARM_PREFER_MINIMAL 选择 Minimal / 完整版 ——
        for version in ["24.04", "22.04"]:
            for img in images:
                name = (img.display_name or "").lower()
                if version not in name or "aarch64" not in name:
                    continue
                is_minimal = "minimal" in name
                if ARM_PREFER_MINIMAL == is_minimal:
                    print(f"Selected image: {img.display_name}")
                    return img.id
        # 兜底：任意 aarch64
        for img in images:
            if "aarch64" in (img.display_name or "").lower():
                print(f"Fallback image: {img.display_name}")
                return img.id
        raise Exception("Ubuntu aarch64 ARM image not found")

    else:
        # —— x86：不能带 aarch64，优先完整版，兜底 Minimal ——
        for version in ["24.04", "22.04"]:
            for img in images:
                name = (img.display_name or "").lower()
                if version in name and "aarch64" not in name and "minimal" not in name:
                    print(f"Selected image: {img.display_name}")
                    return img.id
        # 兜底：任意不带 aarch64 的镜像
        for img in images:
            if "aarch64" not in (img.display_name or "").lower():
                print(f"Fallback image: {img.display_name}")
                return img.id
        raise Exception("Ubuntu x86 image not found")


def ensure_vcn(network):
    """确保 VCN、互联网网关、路由表、安全列表已存在"""
    vcns = network.list_vcns(COMPARTMENT_ID, display_name=VCN_NAME).data
    if vcns:
        print(f"Using existing VCN: {vcns[0].id}")
        return vcns[0]

    vcn = network.create_vcn(
        oci.core.models.CreateVcnDetails(
            compartment_id=COMPARTMENT_ID,
            display_name=VCN_NAME,
            cidr_block=VCN_CIDR,
        )
    ).data
    print(f"Created VCN: {vcn.id}")

    ig = network.create_internet_gateway(
        oci.core.models.CreateInternetGatewayDetails(
            compartment_id=COMPARTMENT_ID,
            vcn_id=vcn.id,
            display_name=VCN_NAME + "-ig",
            is_enabled=True,
        )
    ).data

    network.update_route_table(
        vcn.default_route_table_id,
        oci.core.models.UpdateRouteTableDetails(
            route_rules=[
                oci.core.models.RouteRule(
                    destination="0.0.0.0/0",
                    network_entity_id=ig.id,
                )
            ]
        ),
    )

    security_lists = network.list_security_lists(COMPARTMENT_ID, vcn_id=vcn.id).data
    if security_lists:
        existing_egress = security_lists[0].egress_security_rules
        new_ingress = []
        for port in [22, 80, 443, 8501]:
            new_ingress.append(
                oci.core.models.IngressSecurityRule(
                    protocol="6",
                    source="0.0.0.0/0",
                    tcp_options=oci.core.models.TcpOptions(
                        destination_port_range=oci.core.models.PortRange(
                            min=port, max=port
                        )
                    ),
                )
            )
        network.update_security_list(
            security_lists[0].id,
            oci.core.models.UpdateSecurityListDetails(
                ingress_security_rules=new_ingress,
                egress_security_rules=existing_egress,
            ),
        )

    return vcn


def ensure_subnet(network, vcn):
    subnets = network.list_subnets(
        COMPARTMENT_ID, vcn_id=vcn.id, display_name=SUBNET_NAME
    ).data
    if subnets:
        print(f"Using existing subnet: {subnets[0].id}")
        return subnets[0].id

    subnet = network.create_subnet(
        oci.core.models.CreateSubnetDetails(
            compartment_id=COMPARTMENT_ID,
            vcn_id=vcn.id,
            display_name=SUBNET_NAME,
            cidr_block=SUBNET_CIDR,
            prohibit_public_ip_on_vnic=False,
        )
    ).data
    print(f"Created subnet: {subnet.id}")
    return subnet.id


def try_create_instance(subnet_id, ad_name, image_id):
    compute = oci.core.ComputeClient(config)

    details = oci.core.models.LaunchInstanceDetails(
        compartment_id=COMPARTMENT_ID,
        display_name=INSTANCE_NAME,
        availability_domain=ad_name,
        shape=SHAPE,
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id,
            boot_volume_size_in_gbs=BOOT_VOLUME_SIZE_IN_GBS,
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet_id,
            assign_public_ip=True,
        ),
        metadata={"ssh_authorized_keys": SSH_PUBLIC_KEY},
    )

    # 只有 A1.Flex 需要 shape_config，E2.1.Micro 不能带
    if HAS_SHAPE_CONFIG:
        details.shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=ARM_OCPUS,
            memory_in_gbs=ARM_MEMORY_IN_GBS,
        )

    return compute.launch_instance(details).data


def main():
    print(f"=== 目标架构: {TARGET_ARCH.upper()} ===")
    print(f"=== Shape: {SHAPE} ===")
    if HAS_SHAPE_CONFIG:
        print(f"=== 规格: {ARM_OCPUS} OCPU / {ARM_MEMORY_IN_GBS} GB ===")

    print("Initializing network configuration...")
    network = oci.core.VirtualNetworkClient(config)
    vcn = ensure_vcn(network)
    subnet_id = ensure_subnet(network, vcn)

    print("Fetching availability domains...")
    ad_names = get_availability_domains()
    print(f"Available ADs: {ad_names}")

    print("Fetching image...")
    image_id = get_image()
    print(f"Image ID: {image_id}")

    attempt = 0
    while True:
        attempt += 1
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] === Round #{attempt} ===")

        for ad in ad_names:
            try:
                instance = try_create_instance(subnet_id, ad, image_id)
                print(f"\n✅ Success! Instance created in {ad}")
                print(f"   ID: {instance.id}")
                print(f"   State: {instance.lifecycle_state}")
                print(f"   Check Oracle Cloud Console for the public IP")
                return
            except oci.exceptions.ServiceError as e:
                msg = str(e).lower()
                if "capacity" in msg:
                    print(f"❌ {ad}: Out of capacity")
                else:
                    print(f"❌ {ad}: API error: {e.message}")
            except Exception as e:
                print(f"⚠️ {ad}: {type(e).__name__}: {e}")

        print(f"All ADs exhausted. Sleeping {RETRY_INTERVAL}s...")
        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
