from agents.tier1_router import Tier1Router

router = Tier1Router()

test_cases = [
    # Dễ hiểu
    ("Ngựa đua thuần chủng", "SECTION_I"),
    ("Gạo ST25 xuất khẩu", "SECTION_II"),
    ("Dầu hướng dương tinh luyện", "SECTION_III"),
    ("Rượu vang đỏ Bordeaux", "SECTION_IV"),
    ("Quặng sắt thô", "SECTION_V"),
    
    # Khó / Dễ nhầm lẫn
    ("Máy tính xách tay (Laptop)", "SECTION_XVI"), # Điện tử, không phải đồ nhựa dù vỏ nhựa
    ("Áo phông cotton nam", "SECTION_XI"), # Dệt may
    ("Giày thể thao đế cao su vãi lưới", "SECTION_XII"), # Giày dép
    ("Bàn ghế gỗ phòng khách", "SECTION_XX"), # Đồ nội thất (XX), không phải Gỗ (IX)
    ("Chó robot đồ chơi bằng nhựa", "SECTION_XX"), # Đồ chơi (XX), không phải động vật sống (I) hay máy móc (XVI)
    ("Súng trường bắn tỉa quân dụng", "SECTION_XIX"), # Vũ khí
    ("Đường ray tàu hỏa bằng thép", "SECTION_XV"), # Sắt thép (XV)
    ("Tàu hỏa chạy điện", "SECTION_XVII"), # Phương tiện giao thông
    ("Đồng hồ đeo tay có vỏ bằng vàng nguyên khối", "SECTION_XVIII"), # Đồng hồ (XVIII), không phải trang sức vàng (XIV)
    ("Nhẫn kim cương đính ngọc trai", "SECTION_XIV") # Trang sức quý
]

print("="*60)
print("BẮT ĐẦU TEST LAYER DETECT SECTION (ZERO-SHOT CROSS-LINGUAL)")
print("="*60)

passed = 0
for idx, (desc, expected) in enumerate(test_cases, 1):
    print(f"\n[Test {idx}/{len(test_cases)}] Hàng hóa: '{desc}'")
    result = router.route_to_section(desc)
    
    if result == expected:
        print(f"✅ PASSED (Expected: {expected}, Got: {result})")
        passed += 1
    else:
        print(f"❌ FAILED (Expected: {expected}, Got: {result})")

print("\n" + "="*60)
print(f"KẾT QUẢ: {passed}/{len(test_cases)} ({passed/len(test_cases)*100:.1f}%) TEST CASES THÀNH CÔNG.")
print("="*60)
