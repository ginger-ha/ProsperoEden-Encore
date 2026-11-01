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


## Native image sizing — commands 435 and 1510

The research supervisor also forwards TIPC 435 (size) and 1510
(size plus alignment) to the already tested
`CalculateNativeImageRequirements` helper. That helper supports only reviewed
block-linear four-byte-color layouts, validates the sixteen preference words,
checks size/count arithmetic and returns 4096-byte alignment. Unrecognized
formats or malformed word counts receive a kernel error, not a fabricated
size. This allows native image resource **planning**, not image creation,
Vulkan submission or first-frame presentation.

## Real NVMap native-memory ownership — November 1 integration

The research GSV now uses **real global NVMap handle IDs** instead of private
metadata-only IDs for TIPC 111. Command 114 checks its strict nine-word
packet, exact owned allocation size, guest mapped pages and (for flags=2)
GpuAccessible pages, then locks the guest pages for device mapping and calls
NVMap::Handle::Alloc with an owned NVDRV session. Partial failures roll back
the page-table lock. Command 112 rejects busy/pinned handles, drops temporary
shared_ptr ownership *before* FreeHandle, and releases the mapped page-table
lock only after NVMap confirms final ownership. Supervisor destruction drains
its remaining unborrowed allocations before closing the NVDRV session.

The GPU worker previously held a temporary shared_ptr across FreeHandle,
causing NVMap to report can_unlock=false even for a released resource. That
reference was corrected in the same vendor lot, before the GSV backend.

This is **actual backing ownership**, not a Vulkan VkImage, Ampere shader
execution or VI2 present path. Command 429 remains unsupported until the
native image registry and renderer can consume a correctly retained backing.
No Switch 1 release source has been replaced by this change.

## Native image registry 429/430 (research only)

Commands **429** and **430** are now routed through a bounded 1024-image
registry. Creating an image requires the known 16-word block-linear layout,
a fully allocated and bound NVMap backing handle large enough for its
calculated size, and an actual NVMap internal duplicate. Destroying the image
releases that internal duplicate and its unique logical image ID. Unreleased
images retain the backing until supervisor teardown drains those references.
This is the same resource-lifetime dependency used by the upstream GSV; the
PS5 Vulkan/VI2 image consumer, Ampere lowering and final screen presentation
remain to be integrated and proven on console. Unsupported formats fail.

## Parent-backed native GPU memory (TIPC 423, research only)

Command **423** now decodes the exact 14-word native parent-binding packet,
rejects nonzero reserved words, self-parenting, unaligned or wrapping ranges,
and confirms that the allocated parent NVMap handle comes from the same
KProcess. The parent's virtual offset must equal the requested child address,
and the full child range must fit. The parent is internally duplicated and
pinned before the child uses the same real page-table lock and NVMap allocation
helper as command 114. Every failure before commit rolls back its pin and
duplicate. The child records its parent, and command 112 releases that parent
only after the child's resource is actually retired. On session teardown,
the supervisor makes two bounded release passes so an owned parent that was
pinned by a child can be released after that child. Externally borrowed or
busy resources are never forcibly unlocked.

The resource-lifetime code is native GPU preparation, not yet a PS5 Vulkan
image allocation, 4K GPU shader execution or presentation. The NS1 renderer
and ordinary release selectors are unchanged.
