# Bytedance Seedance 2.5

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/jobs/createTask:
    post:
      summary: Bytedance Seedance 2.5
      deprecated: false
      description: >
        ## Query Task Status


        After submitting a task, use the unified query endpoint to check
        progress and retrieve results:


        <Card title="Get Task Details" icon="lucide-search"
        href="/market/common/get-task-detail">
          Learn how to query task status and retrieve generation results
        </Card>


        ::: tip[]

        In production environments, it is recommended to use the callBackUrl
        parameter to receive automatic notifications upon completion, rather
        than polling the status API.

        :::


        > **Note**

        >

        > *   **Image-to-Video (First Frame)**, **Image-to-Video (First & Last
        Frames)**, and **Multimodal Reference-to-Video** (including reference
        images, videos, and audio) are three mutually exclusive scenarios and
        **cannot be used simultaneously**.

        > *   Multimodal Reference-to-Video can indirectly achieve a "First/Last
        Frame + Multimodal Reference" effect by specifying reference images as
        the first or last frame via prompts. If you need to strictly guarantee
        that the first and last frames are identical to the specified images,
        **prioritize using Image-to-Video (First & Last Frames)**




        ## Key Features


        <CardGroup cols={2}>
          <Card title="Text-to-Video" icon="lucide-wand-sparkles">
            Generate videos directly from text descriptions without input images
          </Card>
          <Card title="Image-to-Video" icon="lucide-images">
            Animate static images with 0-2 input images support
          </Card>
          <Card title="Dynamic Camera" icon="lucide-camera">
            Advanced camera movement with optional lens locking for stable shots
          </Card>
          <Card title="Audio Generation" icon="lucide-volume-2">
            Optional audio generation for enhanced video content
          </Card>
        </CardGroup>


        ## Related Resources


        <CardGroup cols={2}>
          <Card title="Market Overview" icon="lucide-store" href="/market/quickstart">
            Explore all available models
          </Card>
          <Card title="Common API" icon="lucide-cog" href="/common-api/get-account-credits">
            Check credits and account usage
          </Card>
        </CardGroup>
      operationId: bytedance-seedance-2-5
      tags:
        - docs/en/Market/Video Models/Bytedance
      parameters: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required:
                - model
                - input
              properties:
                model:
                  type: string
                  description: |-
                    The model name to use for generation. Required field.

                    - Must be `bytedance/seedance-2-5` for this endpoint
                  enum:
                    - bytedance/seedance-2-5
                  default: bytedance/seedance-2-5
                  x-apidog-enum:
                    - value: bytedance/seedance-2-5
                      name: ''
                      description: ''
                  examples:
                    - bytedance/seedance-2-5
                callBackUrl:
                  type: string
                  format: uri
                  description: >-
                    The URL to receive generation task completion updates.
                    Optional but recommended for production use.


                    - System will POST task status and results to this URL when
                    generation completes

                    - Callback includes generated content URLs and task
                    information

                    - Your callback endpoint should accept POST requests with
                    JSON payload containing results

                    - Alternatively, use the Get Task Details endpoint to poll
                    task status

                    - To ensure callback security, see [Webhook Verification
                    Guide](/common-api/webhook-verification) for signature
                    verification implementation
                  examples:
                    - https://your-domain.com/api/callback
                input:
                  type: object
                  description: Input parameters for the generation task
                  properties:
                    prompt:
                      type: string
                      description: >-
                        The text prompt used to generate the video.. ( Max
                        length: 30000 characters)
                      maxLength: 30000
                      examples:
                        - >-
                          A serene beach at sunset with waves gently crashing on
                          the shore, palm trees swaying in the breeze, and
                          seagulls flying across the orange sky
                    first_frame_url:
                      type: string
                      description: >-
                        First frame image url or asset://{assetId} 

                        (for example: asset://asset-20260404242101-76djj)

                        Cannot be used simultaneously with reference_image_urls,
                        reference_video_urls, or reference_audio_urls.
                    last_frame_url:
                      type: string
                      description: >-
                        End frame image url or asset://{assetId} 

                        (for example: asset://asset-20260404242101-76djj)

                        last_frame_url cannot be passed alone; first_frame_url
                        must be provided together with it.
                    reference_image_urls:
                      type: array
                      items:
                        type: string
                        format: uri
                      description: >-
                        Enter a list of image URLs or asset://{assetId} (for
                        example: asset://asset-20260404242101-76djj).

                        Single image requirements:

                        Format: jpeg, png, webp, bmp, tiff, gif.

                        Aspect ratio (width/height): (0.4, 2.5)

                        Width and height (px): (300, 6000)

                        Size: Single image less than 30 MB.

                        Maximum number of files: The sum of the number of frames
                        at the beginning and end must not exceed 30.

                        Mutually exclusive with the first/last-frame scenario;
                      maxItems: 30
                      examples:
                        - - >-
                            https://file.aiquickdraw.com/custom-page/akr/section-images/example1.png
                    reference_video_urls:
                      type: array
                      items:
                        type: string
                        format: uri
                      description: >-
                        Enter a list of video URLs or asset://{assetId} (for
                        example: asset://asset-20260404242101-76djj) .

                        Single video requirements:

                        Video format: mp4, mov.

                        Resolution: 480p, 720p

                        Dimensions:

                        Aspect ratio (width/height): [0.4, 2.5]

                        Width/height (px): [300, 6000]

                        Total pixels: [640×640=409600, 834×1112=927408], i.e.,
                        the product of width and height must meet the range
                        requirement of [409600, 927408].

                        Size: Single video not exceeding 200 MB.

                        Frame rate (FPS): [24, 60]

                        Single video duration: [2, 30] seconds; 

                        Mutually exclusive with the first/last-frame scenario;
                        Total duration of reference videos must not exceed 30
                        seconds.
                      maxItems: 10
                    reference_audio_urls:
                      type: array
                      items:
                        type: string
                        format: uri
                      description: >-
                        Enter a list of audio URLs or asset://{assetId} (for
                        example: asset://asset-20260404242101-76djj) .

                        Single audio requirements:

                        Format: wav, mp3

                        Size: Single audio file size not exceeding 15 MB.

                        Single audio duration: [2, 30] seconds; 

                        Mutually exclusive with the first/last-frame scenario;
                        Total duration of reference videos must not exceed 30
                        seconds.
                      maxItems: 10
                    return_last_frame:
                      type: boolean
                      description: >-
                        Whether to return the last frame of the video. When
                        draft=true, this parameter cannot be set to true.
                      default: false
                    generate_audio:
                      description: |-
                        Whether to generate audio for the video.

                        - **true**: Generate with audio (higher cost)
                        - **false**: Generate without audio

                        Note: Enabling audio will increase the generation cost
                      type: boolean
                      default: true
                      examples:
                        - false
                    resolution:
                      type: string
                      description: >-
                        Video resolution - 480p for faster generation, 720p for
                        balance.
                      enum:
                        - 480p
                        - 720p
                      default: 720p
                      examples:
                        - 720p
                      x-apidog-enum:
                        - value: 480p
                          name: ''
                          description: ''
                        - value: 720p
                          name: ''
                          description: ''
                    aspect_ratio:
                      type: string
                      description: 'Video aspect ratio configuration. '
                      enum:
                        - '1:1'
                        - '4:3'
                        - '3:4'
                        - '16:9'
                        - '9:16'
                        - '21:9'
                        - adaptive
                      default: adaptive
                      x-apidog-enum:
                        - value: '1:1'
                          name: ''
                          description: ''
                        - value: '4:3'
                          name: ''
                          description: ''
                        - value: '3:4'
                          name: ''
                          description: ''
                        - value: '16:9'
                          name: ''
                          description: ''
                        - value: '9:16'
                          name: ''
                          description: ''
                        - value: '21:9'
                          name: ''
                          description: ''
                        - value: adaptive
                          name: ''
                          description: ''
                      examples:
                        - adaptive
                    duration:
                      type: integer
                      description: |-
                        Video duration in 4-30 seconds.
                        Special values -1:
                         Pass -1 for automatic duration selection — the model picks a suitable duration itself (for video-editing tasks, it matches the input video's length; for other task types, it selects within the valid range), instead of you specifying an exact value.
                      default: 5
                      examples:
                        - 5
                    output_format:
                      type: string
                      description: Video output format.
                      enum:
                        - mp4
                        - mov
                      x-apidog-enum:
                        - value: mp4
                          name: ''
                          description: ''
                        - value: mov
                          name: ''
                          description: ''
                      default: mp4
                      examples:
                        - mp4
                    web_search:
                      type: boolean
                      description: Enable online search?
                    nsfw_checker:
                      type: boolean
                      description: >-
                        Defaults to false. You can set it to false based on your
                        needs. If set to false, our content filtering will be
                        disabled, and all results will be returned directly by
                        the model itself.

                        Note: There is no guarantee that everything can be
                        filtered out; if you are not satisfied with the results,
                        you will need to make your own arrangements.
                  x-apidog-orders:
                    - prompt
                    - first_frame_url
                    - last_frame_url
                    - reference_image_urls
                    - reference_video_urls
                    - reference_audio_urls
                    - return_last_frame
                    - generate_audio
                    - resolution
                    - aspect_ratio
                    - duration
                    - output_format
                    - web_search
                    - 01KWKMN7PBRAKVAWC9BZ3PW3YJ
                  x-apidog-refs:
                    01KWKMN7PBRAKVAWC9BZ3PW3YJ:
                      $ref: '#/components/schemas/nsfw_checker'
                  x-apidog-ignore-properties:
                    - nsfw_checker
              x-apidog-orders:
                - model
                - callBackUrl
                - input
              x-apidog-ignore-properties: []
            example: |-
              {
                  "model": "bytedance/seedance-2-5",
                  "callBackUrl": "https://your-domain.com/api/callback",
                  "input": {
                      "prompt": "A serene beach at sunset with waves gently crashing on the shore, palm trees swaying in the breeze, and seagulls flying across the orange sky",
                      "reference_image_urls": [
                          "https://templateb.aiquickdraw.com/custom-page/akr/section-images/example1.png"
                      ],
                      "reference_video_urls": [
                          "https://templateb.aiquickdraw.com/custom-page/akr/section-images/example1.mp4"
                      ],
                      "reference_audio_urls": [
                          "https://templateb.aiquickdraw.com/custom-page/akr/section-images/example1.mp3"
                      ],
                      "return_last_frame": false,
                      "generate_audio": false,
                      "resolution": "720p",
                      "aspect_ratio": "16:9",
                      "duration": 15,
                  }
              }
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
              example:
                code: 200
                msg: success
                data:
                  taskId: task_bytedance_1765186743319
          headers: {}
          x-apidog-name: ''
      security:
        - BearerAuth: []
          x-apidog:
            schemeGroups:
              - id: kn8M4YUlc5i0A0179ezwx
                schemeIds:
                  - BearerAuth
            required: true
            use:
              id: kn8M4YUlc5i0A0179ezwx
            scopes:
              kn8M4YUlc5i0A0179ezwx:
                BearerAuth: []
      x-apidog-folder: docs/en/Market/Video Models/Bytedance
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-39529049-run
components:
  schemas:
    nsfw_checker:
      type: object
      properties:
        nsfw_checker:
          type: boolean
          description: >-
            Defaults to false. You can set it to false based on your needs. If
            set to false, our content filtering will be disabled, and all
            results will be returned directly by the model itself.

            Note: There is no guarantee that everything can be filtered out; if
            you are not satisfied with the results, you will need to make your
            own arrangements.
      x-apidog-orders:
        - nsfw_checker
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
    ApiResponse:
      type: object
      properties:
        code:
          type: integer
          description: >-
            Response status code


            - **200**: Success - Request has been processed successfully

            - **401**: Unauthorized - Authentication credentials are missing or
            invalid

            - **402**: Insufficient Credits - Account does not have enough
            credits to perform the operation

            - **404**: Not Found - The requested resource or endpoint does not
            exist

            - **422**: Validation Error - The request parameters failed
            validation checks

            - **429**: Rate Limited - Request limit has been exceeded for this
            resource

            - **433**: Request Limit - Sub-key Usage Exceeds Limit

            - **455**: Service Unavailable - System is currently undergoing
            maintenance

            - **500**: Server Error - An unexpected error occurred while
            processing the request

            - **501**: Generation Failed - Content generation task failed

            - **505**: Feature Disabled - The requested feature is currently
            disabled
          enum:
            - 200
            - 401
            - 402
            - 404
            - 422
            - 429
            - 433
            - 455
            - 500
            - 501
            - 505
          x-apidog-enum:
            - value: 200
              name: ''
              description: ''
            - value: 401
              name: ''
              description: ''
            - value: 402
              name: ''
              description: ''
            - value: 404
              name: ''
              description: ''
            - value: 422
              name: ''
              description: ''
            - value: 429
              name: ''
              description: ''
            - value: 433
              name: ''
              description: ''
            - value: 455
              name: ''
              description: ''
            - value: 500
              name: ''
              description: ''
            - value: 501
              name: ''
              description: ''
            - value: 505
              name: ''
              description: ''
        msg:
          type: string
          description: Response message, error description when failed
          examples:
            - success
        data:
          type: object
          properties:
            taskId:
              type: string
              description: >-
                Task ID, can be used with Get Task Details endpoint to query
                task status
          x-apidog-orders:
            - taskId
          required:
            - taskId
          x-apidog-ignore-properties: []
      x-apidog-orders:
        - code
        - msg
        - data
      title: response not with recordId
      required:
        - data
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
  securitySchemes:
    BearerAuth:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: >-
        All API requests require a Bearer Token. Add the header `Authorization:
        Bearer YOUR_API_KEY` to authenticate requests.
    BearerAuth1:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: >-
        所有 API 请求都需要 Bearer Token。请在请求头中添加 `Authorization: Bearer YOUR_API_KEY`
        进行身份验证。
servers:
  - url: https://api.kie.ai
    description: 正式环境
security:
  - BearerAuth: []
    x-apidog:
      schemeGroups:
        - id: kn8M4YUlc5i0A0179ezwx
          schemeIds:
            - BearerAuth
      required: true
      use:
        id: kn8M4YUlc5i0A0179ezwx
      scopes:
        kn8M4YUlc5i0A0179ezwx:
          BearerAuth: []

```
