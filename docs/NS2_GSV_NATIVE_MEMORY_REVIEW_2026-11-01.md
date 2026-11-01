# NS2 GSV memory objects (111/112/114) — research integration

A real Switch 2 graphics session cannot initialize image resources without
valid native-memory handles. This pass adapts the upstream Eglantine nx2 GSV
native-memory command envelope into Encore's **isolated research** supervisor.

- Command **111** creates a unique owned native-memory descriptor after GPU
  bootstrap. No host PS5 RAM or Vulkan image is allocated by this command.
- Command **114** binds an existing handle to validated, fully mapped guest
  virtual-memory ranges. It rejects unaligned/overflow/oversized ranges,
  inaccessible/unmapped pages and repeat binding.
- Command **112** destroys the exact descriptor; stale and unknown IDs fail.
  Creation is capped at 2048 objects and 12 GiB per object.
- Command **423** (parent GPU memory), native image creation **429**, VI2
  presentation, GPU workers and Ampere execution remain separate work; no
  blind success fallback is added.
- The shared NS1 renderer and release GSV path remain unchanged. These
  handlers are compiled only under EDEN_NS2_GRAPHICS_SUPERVISOR_EXPERIMENTAL.

The source-linked C++20 test tools/ns2/test_graphics_hle.cpp exercises
bounds, creation, binding, rebind, resource identity and destruction under
O0/O2 UBSan. The preflight tool checks dispatch wiring to the real source.
Successful tests do not establish first PS5 frame or gameplay compatibility.
