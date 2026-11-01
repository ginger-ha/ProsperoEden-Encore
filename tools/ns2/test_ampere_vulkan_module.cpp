// SPDX-License-Identifier: GPL-3.0-or-later
// Test the real Vulkan loader's shader-module ABI using generated synthetic SPIR-V.
// Host-only: NO VkGraphicsPipeline and NO PS5/real guest GPU execution.
#include <vulkan/vulkan.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>
#include <cstdint>

static void Require(bool ok, const char* detail) {
    if (!ok) { std::fprintf(stderr,"NS2 Vulkan module test: %s\n",detail); std::exit(1); }
}
static std::vector<uint32_t> ReadSpirv(const char* file) {
    std::ifstream stream{file,std::ios::binary|std::ios::ate};
    Require(bool(stream),"cannot open generated SPIR-V");
    const auto length=stream.tellg();
    Require(length>=static_cast<std::streampos>(20) &&
            static_cast<std::streamoff>(length)%4==0 &&
            length<=static_cast<std::streampos>(1024*1024),
            "SPIR-V must be bounded and 4-byte aligned");
    std::vector<uint32_t> words(static_cast<std::size_t>(length)/4);
    stream.seekg(0);
    stream.read(reinterpret_cast<char*>(words.data()),length);
    Require(bool(stream)&&words[0]==0x07230203U,"invalid SPIR-V payload");
    return words;
}
int main(int argc,char** argv) {
    Require(argc==5,"expected direct, dispatcher, Fragment and merged modules");
    VkApplicationInfo application{};
    application.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO;
    application.pApplicationName="NS2 synthetic shader module smoke test";
    application.apiVersion=VK_API_VERSION_1_2;
    VkInstanceCreateInfo instance_info{};
    instance_info.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    instance_info.pApplicationInfo=&application;
    VkInstance instance=VK_NULL_HANDLE;
    Require(vkCreateInstance(&instance_info,nullptr,&instance)==VK_SUCCESS,
            "no Vulkan 1.2 instance");
    uint32_t count=0;
    Require(vkEnumeratePhysicalDevices(instance,&count,nullptr)==VK_SUCCESS && count>0,
            "no Vulkan software/host GPU available");
    std::vector<VkPhysicalDevice> devices(count);
    Require(vkEnumeratePhysicalDevices(instance,&count,devices.data())==VK_SUCCESS,
            "physical device enumeration failed");
    VkPhysicalDevice selected=VK_NULL_HANDLE;
    uint32_t queue=0;
    for (auto physical:devices) {
        VkPhysicalDeviceProperties props{};
        vkGetPhysicalDeviceProperties(physical,&props);
        if (props.apiVersion<VK_API_VERSION_1_2) continue;
        uint32_t queues=0;
        vkGetPhysicalDeviceQueueFamilyProperties(physical,&queues,nullptr);
        std::vector<VkQueueFamilyProperties> families(queues);
        vkGetPhysicalDeviceQueueFamilyProperties(physical,&queues,families.data());
        for (uint32_t i=0;i<queues;++i) {
            if (families[i].queueCount && (families[i].queueFlags&VK_QUEUE_GRAPHICS_BIT)) {
                selected=physical; queue=i; break;
            }
        }
        if (selected) {
            std::printf("Vulkan device: %s (API %u.%u)\n",props.deviceName,
                        VK_API_VERSION_MAJOR(props.apiVersion),
                        VK_API_VERSION_MINOR(props.apiVersion));
            break;
        }
    }
    Require(selected!=VK_NULL_HANDLE,"no Vulkan >=1.2 graphics queue");
    const float priority=1.0f;
    VkDeviceQueueCreateInfo queue_info{};
    queue_info.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    queue_info.queueFamilyIndex=queue;
    queue_info.queueCount=1;
    queue_info.pQueuePriorities=&priority;
    VkDeviceCreateInfo device_info{};
    device_info.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    device_info.queueCreateInfoCount=1;
    device_info.pQueueCreateInfos=&queue_info;
    VkDevice device=VK_NULL_HANDLE;
    Require(vkCreateDevice(selected,&device_info,nullptr,&device)==VK_SUCCESS,
            "Vulkan device creation failed");
    // A no-attachment render pass and rasterizer-discard pipeline isolate the
    // vertex shader compiler without claiming presentation or fragment rendering.
    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS;
    VkRenderPassCreateInfo render_pass_info{};
    render_pass_info.sType=VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    render_pass_info.subpassCount=1;
    render_pass_info.pSubpasses=&subpass;
    VkRenderPass render_pass=VK_NULL_HANDLE;
    Require(vkCreateRenderPass(device,&render_pass_info,nullptr,&render_pass)==VK_SUCCESS,
            "empty host graphics render pass creation failed");
    VkPipelineLayoutCreateInfo layout_info{};
    layout_info.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    VkPipelineLayout layout=VK_NULL_HANDLE;
    Require(vkCreatePipelineLayout(device,&layout_info,nullptr,&layout)==VK_SUCCESS,
            "synthetic shader pipeline layout creation failed");
    for (int i=1;i<argc;++i) {
        auto code=ReadSpirv(argv[i]);
        VkShaderModuleCreateInfo module_info{};
        module_info.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        module_info.codeSize=code.size()*sizeof(uint32_t);
        module_info.pCode=code.data();
        VkShaderModule shader=VK_NULL_HANDLE;
        const VkResult rc=vkCreateShaderModule(device,&module_info,nullptr,&shader);
        Require(rc==VK_SUCCESS && shader!=VK_NULL_HANDLE,
                "vkCreateShaderModule rejected a synthetic NSW2 module");
        if (i==3) {
            // No fragment linkage or rasterizer output is claimed. Validate
            // Vulkan module creation without reusing the vertex-only pipeline.
            vkDestroyShaderModule(device,shader,nullptr);
            std::printf("vkCreateShaderModule: PASS (native Fragment; no pipeline)\n");
            continue;
        }
        VkPipelineShaderStageCreateInfo stage{};
        stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stage.stage=VK_SHADER_STAGE_VERTEX_BIT;
        stage.module=shader;
        stage.pName="main";
        VkPipelineVertexInputStateCreateInfo vertex_input{};
        vertex_input.sType=VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
        VkPipelineInputAssemblyStateCreateInfo assembly{};
        assembly.sType=VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
        assembly.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
        VkViewport viewport{};
        viewport.width=1;
        viewport.height=1;
        viewport.minDepth=0;
        viewport.maxDepth=1;
        VkRect2D scissor{};
        scissor.extent.width=1;
        scissor.extent.height=1;
        VkPipelineViewportStateCreateInfo viewport_info{};
        viewport_info.sType=VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
        viewport_info.viewportCount=1;
        viewport_info.pViewports=&viewport;
        viewport_info.scissorCount=1;
        viewport_info.pScissors=&scissor;
        VkPipelineRasterizationStateCreateInfo raster{};
        raster.sType=VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
        raster.rasterizerDiscardEnable=VK_TRUE;
        raster.polygonMode=VK_POLYGON_MODE_FILL;
        raster.cullMode=VK_CULL_MODE_NONE;
        raster.frontFace=VK_FRONT_FACE_COUNTER_CLOCKWISE;
        raster.lineWidth=1.0f;
        VkPipelineMultisampleStateCreateInfo multisample{};
        multisample.sType=VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
        multisample.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
        VkPipelineColorBlendStateCreateInfo blend{};
        blend.sType=VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
        VkGraphicsPipelineCreateInfo pipeline_info{};
        pipeline_info.sType=VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
        pipeline_info.stageCount=1;
        pipeline_info.pStages=&stage;
        pipeline_info.pVertexInputState=&vertex_input;
        pipeline_info.pInputAssemblyState=&assembly;
        pipeline_info.pViewportState=&viewport_info;
        pipeline_info.pRasterizationState=&raster;
        pipeline_info.pMultisampleState=&multisample;
        pipeline_info.pColorBlendState=&blend;
        pipeline_info.layout=layout;
        pipeline_info.renderPass=render_pass;
        pipeline_info.subpass=0;
        VkPipeline pipeline=VK_NULL_HANDLE;
        const VkResult compiled=vkCreateGraphicsPipelines(
            device,VK_NULL_HANDLE,1,&pipeline_info,nullptr,&pipeline);
        if (compiled!=VK_SUCCESS) {
            std::fprintf(stderr,"vkCreateGraphicsPipelines returned %d\n",int(compiled));
        }
        Require(compiled==VK_SUCCESS && pipeline!=VK_NULL_HANDLE,
                "Vulkan host rejected the real synthetic vertex pipeline");
        vkDestroyPipeline(device,pipeline,nullptr);
        vkDestroyShaderModule(device,shader,nullptr);
        std::printf("vkCreateShaderModule + vkCreateGraphicsPipelines: PASS (%s)\n",argv[i]);
    }
    // Unlike the vertex-only rasterizer-discard test above, this attempts
    // real graphics-stage linkage. Both shader modules are emitted by the
    // native Ampere-to-Maxwell IR/SPIR-V compiler, not authored GLSL fixtures.
    // Pipeline creation alone cannot establish actual guest rendering.
    auto create_module = [&](const char* path) {
        const auto code = ReadSpirv(path);
        VkShaderModuleCreateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        info.codeSize = code.size() * sizeof(uint32_t);
        info.pCode = code.data();
        VkShaderModule module = VK_NULL_HANDLE;
        Require(vkCreateShaderModule(device, &info, nullptr, &module) == VK_SUCCESS &&
                    module != VK_NULL_HANDLE,
                "cannot create linked graphics stage module");
        return module;
    };
    const VkShaderModule vertex_module = create_module(argv[4]); // merged A+B
    const VkShaderModule fragment_module = create_module(argv[3]);
    VkAttachmentDescription color_attachment{};
    color_attachment.format = VK_FORMAT_R8G8B8A8_UNORM;
    color_attachment.samples = VK_SAMPLE_COUNT_1_BIT;
    color_attachment.loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    color_attachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    color_attachment.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    color_attachment.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    color_attachment.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    color_attachment.finalLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    VkAttachmentReference color_ref{};
    color_ref.attachment = 0;
    color_ref.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    VkSubpassDescription color_subpass{};
    color_subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    color_subpass.colorAttachmentCount = 1;
    color_subpass.pColorAttachments = &color_ref;
    VkRenderPassCreateInfo color_pass_info{};
    color_pass_info.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    color_pass_info.attachmentCount = 1;
    color_pass_info.pAttachments = &color_attachment;
    color_pass_info.subpassCount = 1;
    color_pass_info.pSubpasses = &color_subpass;
    VkRenderPass color_pass = VK_NULL_HANDLE;
    Require(vkCreateRenderPass(device, &color_pass_info, nullptr, &color_pass) ==
                VK_SUCCESS, "cannot create native graphics color render pass");

    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vertex_module;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = fragment_module;
    stages[1].pName = "main";
    VkPipelineVertexInputStateCreateInfo vertex_input{};
    vertex_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    VkPipelineInputAssemblyStateCreateInfo assembly{};
    assembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkViewport viewport{};
    viewport.width = 1.0f;
    viewport.height = 1.0f;
    viewport.maxDepth = 1.0f;
    VkRect2D scissor{};
    scissor.extent.width = 1;
    scissor.extent.height = 1;
    VkPipelineViewportStateCreateInfo viewport_state{};
    viewport_state.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewport_state.viewportCount = 1;
    viewport_state.pViewports = &viewport;
    viewport_state.scissorCount = 1;
    viewport_state.pScissors = &scissor;
    VkPipelineRasterizationStateCreateInfo raster{};
    raster.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    raster.polygonMode = VK_POLYGON_MODE_FILL;
    raster.cullMode = VK_CULL_MODE_NONE;
    raster.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    raster.lineWidth = 1.0f;
    raster.rasterizerDiscardEnable = VK_FALSE;
    VkPipelineMultisampleStateCreateInfo multisample{};
    multisample.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;
    VkPipelineColorBlendAttachmentState blend_attachment{};
    blend_attachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT |
                                      VK_COLOR_COMPONENT_G_BIT |
                                      VK_COLOR_COMPONENT_B_BIT |
                                      VK_COLOR_COMPONENT_A_BIT;
    VkPipelineColorBlendStateCreateInfo blend{};
    blend.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    blend.attachmentCount = 1;
    blend.pAttachments = &blend_attachment;
    VkGraphicsPipelineCreateInfo pipeline_info{};
    pipeline_info.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipeline_info.stageCount = 2;
    pipeline_info.pStages = stages;
    pipeline_info.pVertexInputState = &vertex_input;
    pipeline_info.pInputAssemblyState = &assembly;
    pipeline_info.pViewportState = &viewport_state;
    pipeline_info.pRasterizationState = &raster;
    pipeline_info.pMultisampleState = &multisample;
    pipeline_info.pColorBlendState = &blend;
    pipeline_info.layout = layout;
    pipeline_info.renderPass = color_pass;
    VkPipeline linked_pipeline = VK_NULL_HANDLE;
    const auto linked_result = vkCreateGraphicsPipelines(
        device, VK_NULL_HANDLE, 1, &pipeline_info, nullptr, &linked_pipeline);
    if (linked_result != VK_SUCCESS)
        std::fprintf(stderr, "Linked native graphics pipeline result: %d\\n",
                     static_cast<int>(linked_result));
    Require(linked_result == VK_SUCCESS && linked_pipeline != VK_NULL_HANDLE,
            "native merged VertexA/B and Fragment did not link to a Vulkan pipeline");
    vkDestroyPipeline(device, linked_pipeline, nullptr);
    vkDestroyRenderPass(device, color_pass, nullptr);
    vkDestroyShaderModule(device, fragment_module, nullptr);
    vkDestroyShaderModule(device, vertex_module, nullptr);
    std::puts("NS2 synthetic Vertex/Fragment color pipeline: PASS (host only)");
    vkDestroyPipelineLayout(device,layout,nullptr);
    vkDestroyRenderPass(device,render_pass,nullptr);
    vkDestroyDevice(device,nullptr);
    vkDestroyInstance(instance,nullptr);
    std::puts("NS2 host rasterizer-discard graphics pipelines: PASS; no actual PS5 rendering tested");
}
