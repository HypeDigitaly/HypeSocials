# GPT Image 2 - Image To Image

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
      summary: GPT Image 2 - Image To Image
      deprecated: false
      description: >-
        ## Create Task


        Use this endpoint to create a new image-to-image generation task.


        <Card title="Get Task Details" icon="lucide-search"
        href="/market/common/get-task-detail">
          After submission, use the unified query endpoint to check task progress and retrieve results
        </Card>


        ::: tip[]

        For production use, we recommend providing the `callBackUrl` parameter
        so your service can receive completion notifications instead of polling
        for task status.

        :::


        ## Related Resources


        <CardGroup cols={2}>
          <Card title="Model Marketplace" icon="lucide-store" href="/market/quickstart">
            Explore all available models and capabilities
          </Card>
          <Card title="Common API" icon="lucide-cog" href="/common-api/get-account-credits">
            Check account credits and usage
          </Card>
        </CardGroup>
      operationId: gpt-image-2-image-to-image
      tags:
        - docs/en/Market/Image    Models/GPT Image
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
                  enum:
                    - gpt-image-2-image-to-image
                  default: gpt-image-2-image-to-image
                  description: >-
                    The model name used for generation. This field is required.
                    This endpoint must use the `gpt-image-2-image-to-image`
                    model.
                  examples:
                    - gpt-image-2-image-to-image
                callBackUrl:
                  type: string
                  format: uri
                  description: >-
                    Callback URL for task completion notifications. Optional
                    parameter. If provided, the system will send a POST request
                    to this URL when the task completes, whether it succeeds or
                    fails. If omitted, no callback notification will be sent.
                  examples:
                    - https://your-domain.com/api/callback
                input:
                  type: object
                  description: Input parameters for the image-to-image task.
                  required:
                    - prompt
                    - input_urls
                  properties:
                    prompt:
                      type: string
                      description: Text prompts, up to 20,000 characters.
                      examples:
                        - >-
                          Transform this product image into a premium e-commerce
                          poster style.
                    input_urls:
                      type: array
                      items:
                        type: string
                        format: uri
                      description: Array of input image URLs.
                      examples:
                        - - https://example.com/
                      maxItems: 16
                    aspect_ratio:
                      type: string
                      description: >-
                        The aspect ratio of the generated image is set to auto
                        by default.

                        Note: 5:4 and 4:5 aspect ratios only support 1K images.
                      enum:
                        - auto
                        - '1:1'
                        - '3:2'
                        - '2:3'
                        - '4:3'
                        - '3:4'
                        - '5:4'
                        - '4:5'
                        - '16:9'
                        - '9:16'
                        - '2:1'
                        - '1:2'
                        - '3:1'
                        - '1:3'
                        - '21:9'
                        - '9:21'
                      x-apidog-enum:
                        - label: auto
                          value: auto
                          description: ''
                        - label: '1:1'
                          value: '1:1'
                          description: ''
                        - label: '3:2'
                          value: '3:2'
                          description: ''
                        - label: '2:3'
                          value: '2:3'
                          description: ''
                        - label: '4:3'
                          value: '4:3'
                          description: ''
                        - label: '3:4'
                          value: '3:4'
                          description: ''
                        - label: '5:4'
                          value: '5:4'
                          description: ''
                        - label: '4:5'
                          value: '4:5'
                          description: ''
                        - label: '16:9'
                          value: '16:9'
                          description: ''
                        - label: '9:16'
                          value: '9:16'
                          description: ''
                        - label: '2:1'
                          value: '2:1'
                          description: ''
                        - label: '1:2'
                          value: '1:2'
                          description: ''
                        - label: '3:1'
                          value: '3:1'
                          description: ''
                        - label: '1:3'
                          value: '1:3'
                          description: ''
                        - label: '21:9'
                          value: '21:9'
                          description: ''
                        - value: '9:21'
                          name: ''
                          description: ''
                    resolution:
                      type: string
                      enum:
                        - 1K
                        - 2K
                        - 4K
                      x-apidog-enum:
                        - value: 1K
                          name: ''
                          description: ''
                        - value: 2K
                          name: ''
                          description: ''
                        - value: 4K
                          name: ''
                          description: ''
                      description: >-
                        Image resolution: Note: Images with a 1:1 aspect ratio
                        cannot be converted to 4K images. Images with the aspect
                        ratio set to "auto" or without a specified aspect ratio
                        parameter will only be converted to 1K images;
                        otherwise, the task will fail to create.
                  x-apidog-orders:
                    - prompt
                    - input_urls
                    - aspect_ratio
                    - resolution
                  x-apidog-ignore-properties: []
              x-apidog-orders:
                - model
                - callBackUrl
                - input
              x-apidog-ignore-properties: []
            example:
              model: gpt-image-2-image-to-image
              callBackUrl: https://your-domain.com/api/callback
              input:
                prompt: take a photo with Sam Altman in the conference room
                input_urls:
                  - >-
                    https://static.aiquickdraw.com/tools/example/1776782793756_wrogXTdd.png
                aspect_ratio: auto
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                allOf:
                  - type: object
                    properties:
                      code:
                        type: integer
                        description: >-
                          Response status code


                          - **200**: Success - Request has been processed
                          successfully

                          - **401**: Unauthorized - Authentication credentials
                          are missing or invalid

                          - **402**: Insufficient Credits - Account does not
                          have enough credits to perform the operation

                          - **404**: Not Found - The requested resource or
                          endpoint does not exist

                          - **422**: Validation Error - The request parameters
                          failed validation checks

                          - **429**: Rate Limited - Request limit has been
                          exceeded for this resource

                          - **433**: Request Limit - Sub-key Usage Exceeds Limit

                          - **455**: Service Unavailable - System is currently
                          undergoing maintenance

                          - **500**: Server Error - An unexpected error occurred
                          while processing the request

                          - **501**: Generation Failed - Content generation task
                          failed

                          - **505**: Feature Disabled - The requested feature is
                          currently disabled
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
                              Task ID, can be used with Get Task Details
                              endpoint to query task status
                        x-apidog-orders:
                          - taskId
                        required:
                          - taskId
                        x-apidog-ignore-properties: []
                    x-apidog-orders:
                      - 01KPR08ETH0VJCQNFC9R5B1DJ7
                    required:
                      - data
                    x-apidog-refs:
                      01KPR08ETH0VJCQNFC9R5B1DJ7:
                        $ref: '#/components/schemas/ApiResponse'
                    x-apidog-ignore-properties:
                      - code
                      - msg
                      - data
              example:
                code: 200
                msg: success
                data:
                  taskId: task_gptimage_1765180586443
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
      x-apidog-folder: docs/en/Market/Image    Models/GPT Image
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-33849458-run
components:
  schemas:
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
